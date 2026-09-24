// k6 부하 — 동시 사용자(VUS)가 쉬지 않고 검사를 접수한다(closed model).
// 사용: k6 run -e BASE=http://gateway:8080 -e VUS=200 -e DURATION=30s load.js
import http from 'k6/http';
import { check } from 'k6';

const img = open('/samples/sample_01.jpg', 'b');

export const options = {
  vus: Number(__ENV.VUS || 50),
  duration: __ENV.DURATION || '30s',
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'max'],
  discardResponseBodies: false,
};

export default function () {
  const res = http.post(`${__ENV.BASE}/api/v1/inspections`, {
    lineId: 'LOAD',
    image: http.file(img, 'sample_01.jpg', 'image/jpeg'),
  }, { timeout: '60s' });
  check(res, {
    'created': (r) => r.status === 201,
    'judged': (r) => r.status === 201 && r.json('status') !== 'FAILED',
  });
}
