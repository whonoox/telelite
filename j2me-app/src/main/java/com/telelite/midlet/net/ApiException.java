package com.telelite.midlet.net;

/**
 * Wraps a real IOException - i.e. no HTTP response was received at all
 * (as opposed to a non-2xx response, which is a normal ApiResponse).
 */
public class ApiException extends Exception {

    public ApiException(Exception cause) {
        super(cause.getMessage());
    }
}
