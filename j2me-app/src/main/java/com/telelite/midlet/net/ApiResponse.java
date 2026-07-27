package com.telelite.midlet.net;

public final class ApiResponse {

    public final int status;
    public final String body;

    public ApiResponse(int status, String body) {
        this.status = status;
        this.body = body;
    }
}
