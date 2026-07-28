import os

from telelite import config


def test_index_shows_not_published_when_files_missing(client, app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOADS_PATH", str(tmp_path / "empty"))
    resp = client.get("/download/")
    assert resp.status_code == 200
    assert b"Not published" in resp.data


def test_jad_404_when_missing(client, app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOADS_PATH", str(tmp_path / "empty"))
    resp = client.get("/download/telelite-j2me.jad")
    assert resp.status_code == 404


def _write_fake_build(tmp_path):
    d = tmp_path / "downloads"
    d.mkdir()
    (d / "telelite-j2me.jad").write_text(
        "MIDlet-1: TeleLite,,com.telelite.midlet.TeleLiteMIDlet\n"
        "MIDlet-Jar-URL: telelite-j2me.jar\n"
        "MIDlet-Jar-Size: 4\n"
    )
    (d / "telelite-j2me.jar").write_bytes(b"fake")
    return d


def test_index_shows_install_link_when_files_present(client, app, tmp_path, monkeypatch):
    d = _write_fake_build(tmp_path)
    monkeypatch.setattr(config, "DOWNLOADS_PATH", str(d))
    resp = client.get("/download/")
    assert resp.status_code == 200
    assert b"/download/telelite-j2me.jad" in resp.data


def test_jad_served_with_correct_mimetype(client, app, tmp_path, monkeypatch):
    d = _write_fake_build(tmp_path)
    monkeypatch.setattr(config, "DOWNLOADS_PATH", str(d))
    resp = client.get("/download/telelite-j2me.jad")
    assert resp.status_code == 200
    assert resp.mimetype == "text/vnd.sun.j2me.app-descriptor"


def test_jar_served_with_correct_mimetype(client, app, tmp_path, monkeypatch):
    d = _write_fake_build(tmp_path)
    monkeypatch.setattr(config, "DOWNLOADS_PATH", str(d))
    resp = client.get("/download/telelite-j2me.jar")
    assert resp.status_code == 200
    assert resp.mimetype == "application/java-archive"
    assert resp.data == b"fake"


def test_downloads_path_resolved_relative_to_cwd_not_package_dir(tmp_path, monkeypatch):
    """Regression test: send_from_directory resolves relative paths against
    app.root_path (the telelite/ package dir), not the process cwd -- a bare
    relative DOWNLOADS_PATH must still resolve the same way os.path would
    from the project root, or real downloads silently 404."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "downloads").mkdir(parents=True)
    (tmp_path / "data" / "downloads" / "telelite-j2me.jad").write_text("x")
    monkeypatch.setattr(config, "DOWNLOADS_PATH", "data/downloads")

    from telelite import downloads

    assert downloads._downloads_dir() == str(tmp_path / "data" / "downloads")
    assert downloads._exists("telelite-j2me.jad")
