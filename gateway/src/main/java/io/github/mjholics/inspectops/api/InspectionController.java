package io.github.mjholics.inspectops.api;

import io.github.mjholics.inspectops.domain.Inspection;
import io.github.mjholics.inspectops.domain.InspectionStatus;
import io.github.mjholics.inspectops.domain.LineStatusCount;
import io.github.mjholics.inspectops.service.InspectionService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1")
@Validated
public class InspectionController {

    private final InspectionService service;

    public InspectionController(InspectionService service) {
        this.service = service;
    }

    /**
     * 검사 접수. 추론까지 끝낸 결과를 돌려준다.
     * 추론 실패는 5xx가 아니라 201 + status=FAILED — 접수 자체는 성공했고 기록이 남았기 때문이다.
     */
    @PostMapping(value = "/inspections", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<InspectionView> submit(
            @RequestParam @NotBlank @Pattern(regexp = "[A-Za-z0-9_-]{1,32}") String lineId,
            @RequestParam MultipartFile image) throws IOException {
        if (image.isEmpty()) {
            throw new IllegalArgumentException("빈 이미지");
        }
        Inspection i = service.submit(lineId, image.getBytes(), image.getOriginalFilename());
        return ResponseEntity.status(HttpStatus.CREATED).body(InspectionView.of(i));
    }

    @GetMapping("/inspections/{id}")
    public InspectionView get(@PathVariable UUID id) {
        return InspectionView.of(service.get(id));
    }

    /** 검토 큐 등 상태별 목록 (오래된 순). */
    @GetMapping("/inspections")
    public Page<InspectionView> list(@RequestParam(defaultValue = "NEEDS_REVIEW") InspectionStatus status,
                                     @RequestParam(defaultValue = "0") int page,
                                     @RequestParam(defaultValue = "20") int size) {
        return service.byStatus(status, PageRequest.of(page, Math.min(size, 100))).map(InspectionView::of);
    }

    @PostMapping("/inspections/{id}/review")
    public InspectionView review(@PathVariable UUID id, @Valid @RequestBody ReviewRequest req) {
        return InspectionView.of(service.review(id, req.finalClass(), req.reviewer()));
    }

    @GetMapping("/stats")
    public List<LineStatusCount> stats() {
        return service.stats();
    }

    public record ReviewRequest(@NotBlank String finalClass, @NotBlank String reviewer) {
    }
}
