package io.github.mjholics.inspectops.service;

import io.github.mjholics.inspectops.config.InspectOpsProperties;
import io.github.mjholics.inspectops.domain.Inspection;
import io.github.mjholics.inspectops.domain.InspectionRepository;
import io.github.mjholics.inspectops.domain.InspectionStatus;
import io.github.mjholics.inspectops.domain.LineStatusCount;
import io.github.mjholics.inspectops.inference.InferenceClient;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

/**
 * 검사 작업의 수명주기. 핵심 설계는 트랜잭션 경계다:
 * <pre>
 *   [tx1] PENDING 저장 → (tx 밖) 추론 호출 → [tx2] 결과 반영
 * </pre>
 * 추론 호출을 트랜잭션 안에 두면 느린 추론 동안 DB 커넥션을 쥐고 있게 되고,
 * 커넥션 풀 크기(기본 10)가 곧 동시 처리 상한이 된다.
 * PENDING을 먼저 커밋하는 덕에 Gateway가 추론 도중 죽어도 "접수됐는데 결과 없음"이 DB에 남는다.
 */
@Service
public class InspectionService {

    private final InspectionRepository repository;
    private final InferenceClient inferenceClient;
    private final TransactionTemplate tx;
    private final InspectOpsProperties props;
    private final MeterRegistry meters;
    private final Timer inferenceTimer;
    private final Clock clock;

    public InspectionService(InspectionRepository repository, InferenceClient inferenceClient,
                             TransactionTemplate tx, InspectOpsProperties props,
                             MeterRegistry meters, Clock clock) {
        this.repository = repository;
        this.inferenceClient = inferenceClient;
        this.tx = tx;
        this.props = props;
        this.meters = meters;
        this.clock = clock;
        this.inferenceTimer = Timer.builder("inspectops.inference.call")
                .description("추론 서비스 호출 시간(재시도 포함)")
                .publishPercentileHistogram()
                .register(meters);
    }

    public Inspection submit(String lineId, byte[] image, String filename) {
        Inspection pending = Inspection.pending(lineId, sha256(image), clock.instant());
        tx.executeWithoutResult(s -> repository.save(pending));

        InferenceClient.Outcome outcome = inferenceTimer.record(
                () -> inferenceClient.inspect(image, filename));

        Inspection done = tx.execute(s -> {
            Inspection i = repository.findById(pending.getId()).orElseThrow();
            if (outcome.ok()) {
                i.complete(outcome.result(), outcome.attempts(), props.reviewThreshold(), clock.instant());
            } else {
                i.fail(outcome.error(), outcome.attempts(), clock.instant());
            }
            return i;
        });
        meters.counter("inspectops.inspections", "line", lineId, "status", done.getStatus().name()).increment();
        return done;
    }

    public Inspection get(UUID id) {
        return repository.findById(id).orElseThrow(() -> new NotFoundException("inspection " + id));
    }

    public Page<Inspection> byStatus(InspectionStatus status, Pageable pageable) {
        return repository.findByStatusOrderByCreatedAtAsc(status, pageable);
    }

    public Inspection review(UUID id, String finalClass, String reviewer) {
        return tx.execute(s -> {
            Inspection i = get(id);
            i.review(finalClass, reviewer);
            return i;
        });
    }

    public List<LineStatusCount> stats() {
        return repository.countByLineAndStatus();
    }

    private static String sha256(byte[] data) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    public static class NotFoundException extends RuntimeException {
        public NotFoundException(String message) {
            super(message);
        }
    }
}
