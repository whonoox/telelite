package com.telelite.midlet.net;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import javax.microedition.io.Connector;
import javax.microedition.io.HttpConnection;

public final class ApiClient {

    private static final String BASE_URL = "http://127.0.0.1:5000";

    private ApiClient() {
    }

    public static ApiResponse get(String path, String token) throws ApiException {
        return request(HttpConnection.GET, path, null, token);
    }

    public static ApiResponse post(String path, String jsonBody, String token) throws ApiException {
        return request(HttpConnection.POST, path, jsonBody, token);
    }

    private static ApiResponse request(String method, String path, String jsonBody, String token)
            throws ApiException {
        HttpConnection conn = null;
        OutputStream os = null;
        InputStream is = null;
        try {
            conn = (HttpConnection) Connector.open(BASE_URL + path, Connector.READ_WRITE);
            conn.setRequestMethod(method);
            if (token != null) {
                conn.setRequestProperty("Authorization", "Bearer " + token);
            }
            if (jsonBody != null) {
                byte[] bytes = jsonBody.getBytes("UTF-8");
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                conn.setRequestProperty("Content-Length", String.valueOf(bytes.length));
                os = conn.openOutputStream();
                os.write(bytes);
                os.close();
                os = null;
            }
            int status = conn.getResponseCode();
            is = conn.openInputStream();
            String body = readFully(is);
            return new ApiResponse(status, body);
        } catch (IOException e) {
            throw new ApiException(e);
        } finally {
            if (os != null) {
                try {
                    os.close();
                } catch (IOException ignored) {
                }
            }
            if (is != null) {
                try {
                    is.close();
                } catch (IOException ignored) {
                }
            }
            if (conn != null) {
                try {
                    conn.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static String readFully(InputStream is) throws IOException {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        byte[] buf = new byte[512];
        int n;
        while ((n = is.read(buf)) != -1) {
            baos.write(buf, 0, n);
        }
        return new String(baos.toByteArray(), "UTF-8");
    }
}
