import os

from flask import Blueprint, abort, render_template, send_from_directory

from . import config

bp = Blueprint("downloads", __name__, url_prefix="/download")

# Must exactly match the filenames the J2ME build produces (see
# j2me-app/pom.xml's antrun step) -- the .jad's MIDlet-Jar-URL is a relative
# reference resolved against the .jad's own URL, so the .jar has to be
# reachable at this same path/filename for a phone's OTA installer to find it.
J2ME_JAD_FILENAME = "telelite-j2me.jad"
J2ME_JAR_FILENAME = "telelite-j2me.jar"


def _downloads_dir():
    # Flask's send_from_directory resolves a *relative* directory against
    # app.root_path (the telelite/ package dir), not the process's cwd -- so
    # a bare "data/downloads" would silently look inside telelite/data/downloads
    # instead of <project root>/data/downloads. Resolve to an absolute path
    # up front (cwd-relative, matching how DATABASE_PATH is already resolved
    # elsewhere) so both this and send_from_directory agree on the same spot.
    return os.path.abspath(config.DOWNLOADS_PATH)


def _exists(filename):
    return os.path.isfile(os.path.join(_downloads_dir(), filename))


@bp.route("/", methods=["GET"])
def index():
    return render_template(
        "download.html",
        j2me_available=_exists(J2ME_JAD_FILENAME) and _exists(J2ME_JAR_FILENAME),
    )


@bp.route("/telelite-j2me.jad", methods=["GET"])
def j2me_jad():
    if not _exists(J2ME_JAD_FILENAME):
        abort(404)
    return send_from_directory(
        _downloads_dir(), J2ME_JAD_FILENAME, mimetype="text/vnd.sun.j2me.app-descriptor"
    )


@bp.route("/telelite-j2me.jar", methods=["GET"])
def j2me_jar():
    if not _exists(J2ME_JAR_FILENAME):
        abort(404)
    return send_from_directory(
        _downloads_dir(), J2ME_JAR_FILENAME, mimetype="application/java-archive"
    )
