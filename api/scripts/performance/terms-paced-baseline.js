import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: Number(__ENV.VUS || "1"),
  duration: __ENV.DURATION || "120s",
  discardResponseBodies: true,
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "max"],
  thresholds: {
    checks: ["rate==1"],
    http_req_failed: ["rate==0"]
  }
};

export default function () {
  const response = http.get(
    `${__ENV.BASE_URL}/api/v1/auth/terms`,
    {
      timeout: "15s",
      tags: {
        endpoint: "terms"
      }
    }
  );

  check(response, {
    "HTTP status is 200": (result) => result.status === 200
  });

  sleep(1);
}