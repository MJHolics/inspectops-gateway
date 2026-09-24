package io.github.mjholics.inspectops;

import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

/** 테스트용 추론 서버. 요청마다 큐에서 응답 하나를 꺼내 돌려준다(비면 기본 응답). */
final class FakeInferenceServer implements AutoCloseable {

    record Reply(int status, String body, long delayMs) {
        static Reply ok(String cls, double conf) {
            return new Reply(200, """
                    {"defect_class":"%s","confidence":%s,"severity":"high",
                     "model_version":"fake-v1","model_ms":1.5,"probabilities":{}}
                    """.formatted(cls, conf), 0);
        }

        static Reply status(int code) {
            return new Reply(code, "{\"detail\":\"fake " + code + "\"}", 0);
        }

        static Reply slow(long delayMs) {
            return new Reply(200, ok("scratches", 0.99).body(), delayMs);
        }
    }

    private final HttpServer server;
    private final ConcurrentLinkedQueue<Reply> replies = new ConcurrentLinkedQueue<>();
    private final AtomicInteger hits = new AtomicInteger();

    FakeInferenceServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/v1/inspect", ex -> {
            hits.incrementAndGet();
            ex.getRequestBody().readAllBytes();
            Reply r = replies.poll();
            if (r == null) {
                r = Reply.ok("scratches", 0.97);
            }
            if (r.delayMs() > 0) {
                try {
                    Thread.sleep(r.delayMs());
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            byte[] out = r.body().getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            try {
                ex.sendResponseHeaders(r.status(), out.length);
                try (OutputStream os = ex.getResponseBody()) {
                    os.write(out);
                }
            } catch (IOException ignored) {
                // 클라이언트가 타임아웃으로 먼저 끊은 경우
            }
        });
        server.start();
    }

    String url() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    void enqueue(Reply... rs) {
        for (Reply r : rs) {
            replies.add(r);
        }
    }

    int hits() {
        return hits.get();
    }

    void reset() {
        replies.clear();
        hits.set(0);
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
