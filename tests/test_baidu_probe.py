import hashlib
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytest

from screenlingo.baidu_probe import BaiduProbe, ProbeError, TestBudget as Budget, image_payload


def test_signature_matches_document():
    raw = b"image bytes"
    value = image_payload(raw, "123", "secret", salt="456")
    expected = hashlib.md5(("123" + hashlib.md5(raw).hexdigest() + "456APICUIDmacsecret").encode()).hexdigest()
    assert value["sign"] == expected
    assert value["paste"] == "0"


def test_budget_persists_limits_intervals_duplicates(tmp_path):
    path = tmp_path / "budget.db"
    budget = Budget(path)
    assert budget.reserve("image", 1, "a", now=1000) == 1
    with pytest.raises(ProbeError, match="interval"):
        budget.reserve("image", 1, "b", now=1001)
    with pytest.raises(ProbeError, match="duplicate"):
        Budget(path).reserve("image", 1, "a", now=1010)
    assert budget.reserve("text", 100000, "c", now=1010) == 100000
    with pytest.raises(ProbeError, match="exhausted"):
        budget.reserve("text", 1, "d", now=1020)


def test_parallel_budget_reservations_are_atomic(tmp_path):
    budget = Budget(tmp_path / "budget.db")
    def reserve(i):
        try:
            return budget.reserve("image", 1, str(i), now=1000)
        except ProbeError:
            return None
    with ThreadPoolExecutor(4) as pool:
        assert list(pool.map(reserve, range(4))).count(1) == 1


def test_failed_upload_counted_and_never_retried(tmp_path):
    path = tmp_path / "sample.png"
    cv2.imwrite(str(path), np.full((100, 200, 3), 255, np.uint8))
    class Session:
        calls = 0
        def post(self, url, **kwargs):
            self.calls += 1
            assert kwargs["allow_redirects"] is False
            assert "files" in kwargs
            class Response:
                status_code = 200
                def json(self):
                    return {"error_code": "54001", "error_msg": "secret"}
            return Response()
    session = Session()
    probe = BaiduProbe("123", "secret", Budget(tmp_path / "budget.db"), session)
    with pytest.raises(ProbeError, match="54001") as exc:
        probe.image(path)
    assert "secret" not in str(exc.value)
    with pytest.raises(ProbeError, match="duplicate"):
        probe.image(path)
    assert session.calls == 1


def test_invalid_image_never_spends_budget(tmp_path):
    path = tmp_path / "sample.png"
    cv2.imwrite(str(path), np.zeros((30, 200, 3), np.uint8))
    budget = Budget(tmp_path / "budget.db")
    probe = BaiduProbe("123", "secret", budget)
    with pytest.raises(ProbeError, match="dimensions"):
        probe.image(path)
    assert budget.reserve("image", 1, "valid") == 1
