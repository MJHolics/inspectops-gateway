package io.github.mjholics.inspectops;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.mjholics.inspectops.FakeInferenceServer.Reply;
import io.github.mjholics.inspectops.domain.InspectionRepository;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.io.IOException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@AutoConfigureObservability
class InspectionApiTest {

    static final FakeInferenceServer fake;

    static {
        try {
            fake = new FakeInferenceServer();
        } catch (IOException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry r) {
        r.add("inspectops.inference-url", fake::url);
        r.add("inspectops.read-timeout", () -> "500ms");
        r.add("inspectops.max-attempts", () -> "2");
    }

    @AfterAll
    static void stop() {
        fake.close();
    }

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @Autowired InspectionRepository repository;

    @BeforeEach
    void clean() {
        fake.reset();
        repository.deleteAll();
    }

    private static final MockMultipartFile IMAGE =
            new MockMultipartFile("image", "a.jpg", "image/jpeg", new byte[]{1, 2, 3, 4});

    private JsonNode submit(String line) throws Exception {
        MvcResult res = mvc.perform(multipart("/api/v1/inspections").file(IMAGE).param("lineId", line))
                .andExpect(status().isCreated())
                .andReturn();
        return json.readTree(res.getResponse().getContentAsString());
    }

    @Test
    void 신뢰도가_임계값_이상이면_자동채택되고_저장된다() throws Exception {
        fake.enqueue(Reply.ok("scratches", 0.97));

        JsonNode body = submit("L1");

        assertThat(body.get("status").asText()).isEqualTo("AUTO_ACCEPTED");
        assertThat(body.get("defectClass").asText()).isEqualTo("scratches");
        assertThat(body.get("attempts").asInt()).isEqualTo(1);
        mvc.perform(get("/api/v1/inspections/" + body.get("id").asText()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("AUTO_ACCEPTED"));
    }

    @Test
    void 신뢰도가_낮으면_검토큐로_가고_사람이_확정한다() throws Exception {
        fake.enqueue(Reply.ok("inclusion", 0.55));

        String id = submit("L2").get("id").asText();

        mvc.perform(get("/api/v1/inspections").param("status", "NEEDS_REVIEW"))
                .andExpect(jsonPath("$.content[0].id").value(id));
        mvc.perform(post("/api/v1/inspections/" + id + "/review")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"finalClass\":\"patches\",\"reviewer\":\"qa-kim\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("REVIEWED"))
                .andExpect(jsonPath("$.reviewedClass").value("patches"))
                .andExpect(jsonPath("$.defectClass").value("inclusion"));

        // 이미 확정된 건을 다시 확정할 수 없다
        mvc.perform(post("/api/v1/inspections/" + id + "/review")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"finalClass\":\"crazing\",\"reviewer\":\"qa-lee\"}"))
                .andExpect(status().isConflict());
    }

    @Test
    void 서버오류는_재시도하고_끝내_실패하면_판정없이_FAILED() throws Exception {
        fake.enqueue(Reply.status(503), Reply.status(503));

        JsonNode body = submit("L1");

        assertThat(body.get("status").asText()).isEqualTo("FAILED");
        assertThat(body.get("attempts").asInt()).isEqualTo(2);
        assertThat(body.get("defectClass").isNull()).isTrue();
        assertThat(body.get("confidence").isNull()).isTrue();
        assertThat(fake.hits()).isEqualTo(2);
    }

    @Test
    void 서버오류_뒤_재시도가_성공하면_정상판정() throws Exception {
        fake.enqueue(Reply.status(500), Reply.ok("crazing", 0.91));

        JsonNode body = submit("L1");

        assertThat(body.get("status").asText()).isEqualTo("AUTO_ACCEPTED");
        assertThat(body.get("attempts").asInt()).isEqualTo(2);
    }

    @Test
    void 입력오류_4xx는_재시도하지_않는다() throws Exception {
        fake.enqueue(Reply.status(422));

        JsonNode body = submit("L1");

        assertThat(body.get("status").asText()).isEqualTo("FAILED");
        assertThat(body.get("attempts").asInt()).isEqualTo(1);
        assertThat(fake.hits()).isEqualTo(1);
    }

    @Test
    void 추론이_타임아웃되면_FAILED로_남는다() throws Exception {
        fake.enqueue(Reply.slow(1500), Reply.slow(1500));

        JsonNode body = submit("L3");

        assertThat(body.get("status").asText()).isEqualTo("FAILED");
        assertThat(body.get("errorMessage").asText()).contains("ResourceAccessException");
    }

    @Test
    void 라인별_상태_집계() throws Exception {
        fake.enqueue(Reply.ok("scratches", 0.99), Reply.ok("scratches", 0.30), Reply.ok("patches", 0.95));
        submit("L1");
        submit("L1");
        submit("L2");

        mvc.perform(get("/api/v1/stats"))
                .andExpect(jsonPath("$.length()").value(3))
                .andExpect(jsonPath("$[0].lineId").value("L1"))
                .andExpect(jsonPath("$[0].status").value("AUTO_ACCEPTED"))
                .andExpect(jsonPath("$[0].count").value(1));
    }

    @Test
    void 잘못된_입력은_400_없는_id는_404() throws Exception {
        mvc.perform(multipart("/api/v1/inspections").file(IMAGE).param("lineId", "bad line!"))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/api/v1/inspections/00000000-0000-0000-0000-000000000000"))
                .andExpect(status().isNotFound());
        assertThat(fake.hits()).isZero();
    }

    @Test
    void 프로메테우스_메트릭이_노출된다() throws Exception {
        submit("L1");

        String metrics = mvc.perform(get("/actuator/prometheus"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        assertThat(metrics).contains("inspectops_inspections_total");
        assertThat(metrics).contains("inspectops_inference_call_seconds_bucket");
    }
}
