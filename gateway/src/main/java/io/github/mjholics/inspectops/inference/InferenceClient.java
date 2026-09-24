package io.github.mjholics.inspectops.inference;

import io.github.mjholics.inspectops.config.InspectOpsProperties;
import io.github.mjholics.inspectops.domain.InferenceResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;

/**
 * 추론 서비스 호출. 재시도는 "다시 보내면 결과가 바뀔 수 있는" 실패에만 한다.
 * <ul>
 *   <li>연결 실패·타임아웃(ResourceAccessException), 5xx → 재시도</li>
 *   <li>4xx(깨진 이미지 등) → 즉시 실패. 같은 입력을 다시 보내도 같은 답이다</li>
 * </ul>
 * 추론은 상태가 없어서 재시도해도 부작용(중복 성적서 등)이 생기지 않는다.
 */
@Component
public class InferenceClient {

    private static final Logger log = LoggerFactory.getLogger(InferenceClient.class);

    private final RestClient restClient;
    private final int maxAttempts;

    public InferenceClient(RestClient.Builder builder, InspectOpsProperties props) {
        HttpClient http = HttpClient.newBuilder()
                .connectTimeout(props.connectTimeout())
                .version(HttpClient.Version.HTTP_1_1)
                .build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(http);
        factory.setReadTimeout(props.readTimeout());
        this.restClient = builder
                .baseUrl(props.inferenceUrl())
                .requestFactory(factory)
                .build();
        this.maxAttempts = props.maxAttempts();
    }

    public Outcome inspect(byte[] image, String filename) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("image", new ByteArrayResource(image) {
            @Override
            public String getFilename() {
                return filename;
            }
        });

        String lastError = null;
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                InferenceResult r = restClient.post()
                        .uri("/v1/inspect")
                        .contentType(MediaType.MULTIPART_FORM_DATA)
                        .body(body)
                        .retrieve()
                        .body(InferenceResult.class);
                if (r == null || r.defectClass() == null) {
                    return Outcome.failure("추론 응답에 판정이 없음", attempt);
                }
                return Outcome.success(r, attempt);
            } catch (HttpClientErrorException e) {
                return Outcome.failure("추론 거부 " + e.getStatusCode().value() + ": "
                        + e.getResponseBodyAsString(), attempt);
            } catch (HttpServerErrorException | ResourceAccessException e) {
                lastError = e.getClass().getSimpleName() + ": " + e.getMessage();
                log.warn("추론 호출 실패 attempt={}/{} {}", attempt, maxAttempts, lastError);
            }
        }
        return Outcome.failure(lastError, maxAttempts);
    }

    public record Outcome(InferenceResult result, String error, int attempts) {
        static Outcome success(InferenceResult r, int attempts) {
            return new Outcome(r, null, attempts);
        }

        static Outcome failure(String error, int attempts) {
            return new Outcome(null, error, attempts);
        }

        public boolean ok() {
            return result != null;
        }
    }
}
