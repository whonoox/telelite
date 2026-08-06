package com.telelite.midlet.net;

/**
 * Like ApiResponse but for binary bodies (e.g. avatar images) that must
 * not be decoded as UTF-8 text -- doing so would corrupt arbitrary bytes.
 */
public final class RawResponse {

    public final int status;
    public final byte[] body;

    public RawResponse(int status, byte[] body) {
        this.status = status;
        this.body = body;
    }
}
