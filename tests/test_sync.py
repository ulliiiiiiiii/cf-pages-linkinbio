import io
import json
import urllib.error

import sync


def test_profiles_are_checked(tmp_path):
    (tmp_path / "ok.json").write_text(json.dumps({"name": "Ok", "links": [{"label": "a", "url": "https://example.org"}]}))
    (tmp_path / "Bad Name.json").write_text(json.dumps({"name": "x"}))
    (tmp_path / "broken.json").write_text("{")
    (tmp_path / "wrong.json").write_text(json.dumps({"name": "", "acent": "#fff", "accent": "red",
                                                     "avatar": "http://example.org/a.png",
                                                     "links": [{"url": "javascript:alert(1)"}, {"url": "ftp://x"}]}))
    profiles, problems = sync.load(tmp_path)
    assert list(profiles) == ["ok"]
    text = "\n".join(problems)
    for expected in ("Bad Name: the file name", "broken: not readable", "wrong: unknown field 'acent'",
                     "wrong: name is required", "wrong: accent must", "wrong: avatar must be an https",
                     "wrong: link 1 needs", "wrong: link 2 needs"):
        assert expected in text


def test_dry_run_writes_nothing(tmp_path, capsys):
    (tmp_path / "jane.json").write_text(json.dumps({"name": "Jane", "links": []}))
    assert sync.main(["--profiles", str(tmp_path), "--dry-run"], env={}) == 0
    assert "/jane: Jane, 0 links" in capsys.readouterr().out


class FakeOpener:
    def __init__(self, keys=()):
        self.requests = []
        self.keys = list(keys)

    def open(self, request, timeout=None):
        self.requests.append((request.get_method(), request.full_url, request.data, request.get_header("Authorization")))
        result = [{"name": k} for k in self.keys] if request.full_url.split("?")[0].endswith("/keys") else None
        body = json.dumps({"success": True, "errors": [], "result": result, "result_info": {}}).encode()
        return io.BytesIO(body)


def test_write_and_prune(tmp_path):
    (tmp_path / "jane.json").write_text(json.dumps({"name": "Jane"}))
    opener = FakeOpener(keys=["jane", "old-page"])
    env = {"CLOUDFLARE_API_TOKEN": "t0ken", "CLOUDFLARE_ACCOUNT_ID": "acc", "KV_NAMESPACE_ID": "ns"}
    assert sync.main(["--profiles", str(tmp_path), "--prune"], env=env, opener=opener) == 0
    (method, url, data, auth), _, (dmethod, durl, ddata, _) = opener.requests
    assert (method, url, auth) == ("PUT", f"{sync.API}/accounts/acc/storage/kv/namespaces/ns/bulk", "Bearer t0ken")
    assert json.loads(data) == [{"key": "jane", "value": '{"name": "Jane"}'}]
    assert (dmethod, durl.rsplit("/", 2)[-2:], json.loads(ddata)) == ("POST", ["bulk", "delete"], ["old-page"])


def test_errors_do_not_show_the_token(tmp_path, capsys):
    (tmp_path / "jane.json").write_text(json.dumps({"name": "Jane"}))

    class Refusing:
        def open(self, request, timeout=None):
            body = io.BytesIO(json.dumps({"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}).encode())
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, body)

    env = {"CLOUDFLARE_API_TOKEN": "s3cret-token", "CLOUDFLARE_ACCOUNT_ID": "acc", "KV_NAMESPACE_ID": "ns"}
    assert sync.main(["--profiles", str(tmp_path)], env=env, opener=Refusing()) == 1
    err = capsys.readouterr().err
    assert "10000 Authentication error" in err and "s3cret" not in err


def test_missing_settings(tmp_path, capsys):
    (tmp_path / "jane.json").write_text(json.dumps({"name": "Jane"}))
    assert sync.main(["--profiles", str(tmp_path)], env={}) == 1
    assert "CLOUDFLARE_API_TOKEN" in capsys.readouterr().err
