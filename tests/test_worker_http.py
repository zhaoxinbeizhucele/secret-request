"""HTTP streaming boundaries on the actual local workerd server."""
import http.client
from urllib.parse import urlsplit
import time


def test_slow_json_body_times_out_without_creating_a_request(worker_url):
    parsed = urlsplit(worker_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=22)
    start = time.monotonic()
    try:
        connection.putrequest('POST', '/api/requests')
        connection.putheader('Content-Type', 'application/json')
        connection.putheader('Content-Length', '2')
        connection.endheaders()
        connection.send(b'{')
        response = connection.getresponse()
        assert response.status == 408
        assert response.getheader('Cache-Control') == 'no-store'
        assert 14 <= time.monotonic()-start < 22
    finally:
        connection.close()


def test_chunked_body_limit_does_not_trust_content_length(worker_url):
    parsed = urlsplit(worker_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    try:
        connection.request('POST', '/api/requests', body=iter([b' '*50000, b' '*50001]),
            headers={'Content-Type':'application/json'}, encode_chunked=True)
        assert connection.getresponse().status == 413
    finally:
        connection.close()
