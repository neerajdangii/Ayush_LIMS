import gzip
import json

from django.http import HttpResponse, JsonResponse
from django.middleware.gzip import GZipMiddleware
from django.test import RequestFactory, SimpleTestCase


class GZipResponseTests(SimpleTestCase):
    def test_large_json_is_gzipped_when_the_client_accepts_it(self):
        payload = {"message": "compressible response " * 100}
        request = RequestFactory().get("/api/example/", HTTP_ACCEPT_ENCODING="br, gzip")
        uncompressed = JsonResponse(payload).content
        response = GZipMiddleware(lambda request: JsonResponse(payload))(request)

        self.assertEqual(response["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", response["Vary"])
        self.assertLess(int(response["Content-Length"]), len(uncompressed) / 2)
        self.assertEqual(json.loads(gzip.decompress(response.content)), payload)

    def test_response_is_not_gzipped_without_client_negotiation(self):
        payload = {"message": "compressible response " * 100}
        request = RequestFactory().get("/api/example/")
        response = GZipMiddleware(lambda request: JsonResponse(payload))(request)

        self.assertFalse(response.has_header("Content-Encoding"))
        self.assertEqual(json.loads(response.content), payload)

    def test_already_encoded_response_is_not_compressed_again(self):
        request = RequestFactory().get("/api/example/", HTTP_ACCEPT_ENCODING="gzip")
        original = HttpResponse(b"already compressed", content_type="application/json")
        original["Content-Encoding"] = "br"

        response = GZipMiddleware(lambda request: original)(request)

        self.assertEqual(response["Content-Encoding"], "br")
        self.assertEqual(response.content, b"already compressed")
