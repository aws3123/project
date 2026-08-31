module.exports = {
  baseUrl: __ENV.BASE_URL || 'http://localhost:8080',
  pyBaseUrl: __ENV.PY_BASE_URL || 'http://localhost:8000',
  apiKey: __ENV.API_KEY || 'dev-key',
  stages: {
    imageReview: {
      vu: 50,
      duration: '3m',
    },
    imageDense: {
      vu: 30,
      duration: '3m',
    },
    codeSearch: {
      vu: 40,
      duration: '3m',
    },
    mixed: {
      vu: 100,
      duration: '3m',
    },
    reconnect: {
      vu: 20,
      duration: '3m',
    },
    feedback: {
      vu: 20,
      duration: '3m',
    },
    asyncSubmit: {
      vu: 30,
      duration: '5m',
    },
    dispatchRoute: {
      vu: 20,
      duration: '5m',
    },
  },
  thresholds: {
    imageUrlReplaceSuccess: ['rate>0.998'],
    avgResponseTime: ['avg<180'],
    p95ResponseTime: ['p(95)<500'],
  },
  headers: {
    'X-API-Key': __ENV.API_KEY || 'dev-key',
    'Content-Type': 'application/json',
  },
}
