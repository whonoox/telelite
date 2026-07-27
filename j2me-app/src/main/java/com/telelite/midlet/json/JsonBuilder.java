package com.telelite.midlet.json;

public final class JsonBuilder {

    private final StringBuffer sb = new StringBuffer("{");
    private boolean first = true;

    public JsonBuilder put(String key, String value) {
        if (!first) {
            sb.append(',');
        }
        first = false;
        sb.append('"').append(Json.escape(key)).append("\":\"").append(Json.escape(value)).append('"');
        return this;
    }

    public String build() {
        return sb.toString() + "}";
    }
}
