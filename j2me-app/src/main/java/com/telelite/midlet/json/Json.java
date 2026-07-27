package com.telelite.midlet.json;

import java.util.Hashtable;
import java.util.Vector;

public final class Json {

    public static final Object NULL = new Object();

    public static Object parse(String s) {
        return new Json(s).parseValue();
    }

    public static String escape(String s) {
        StringBuffer sb = new StringBuffer();
        int len = s.length();
        for (int i = 0; i < len; i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':
                    sb.append("\\\"");
                    break;
                case '\\':
                    sb.append("\\\\");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        String hex = Integer.toHexString(c);
                        sb.append("\\u");
                        for (int pad = hex.length(); pad < 4; pad++) {
                            sb.append('0');
                        }
                        sb.append(hex);
                    } else {
                        sb.append(c);
                    }
            }
        }
        return sb.toString();
    }

    private final String s;
    private int pos;

    private Json(String s) {
        this.s = s;
        this.pos = 0;
    }

    private void skipWhitespace() {
        while (pos < s.length()) {
            char c = s.charAt(pos);
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                pos++;
            } else {
                break;
            }
        }
    }

    private Object parseValue() {
        skipWhitespace();
        char c = s.charAt(pos);
        if (c == '{') {
            return parseObject();
        } else if (c == '[') {
            return parseArray();
        } else if (c == '"') {
            return parseString();
        } else if (c == 't' || c == 'f') {
            return parseBoolean();
        } else if (c == 'n') {
            return parseNull();
        } else {
            return parseNumber();
        }
    }

    private Hashtable parseObject() {
        Hashtable obj = new Hashtable();
        pos++; // {
        skipWhitespace();
        if (s.charAt(pos) == '}') {
            pos++;
            return obj;
        }
        while (true) {
            skipWhitespace();
            String key = parseString();
            skipWhitespace();
            pos++; // :
            Object value = parseValue();
            obj.put(key, value);
            skipWhitespace();
            char c = s.charAt(pos);
            if (c == ',') {
                pos++;
                continue;
            } else if (c == '}') {
                pos++;
                break;
            }
        }
        return obj;
    }

    private Vector parseArray() {
        Vector arr = new Vector();
        pos++; // [
        skipWhitespace();
        if (s.charAt(pos) == ']') {
            pos++;
            return arr;
        }
        while (true) {
            Object value = parseValue();
            arr.addElement(value);
            skipWhitespace();
            char c = s.charAt(pos);
            if (c == ',') {
                pos++;
                continue;
            } else if (c == ']') {
                pos++;
                break;
            }
        }
        return arr;
    }

    private String parseString() {
        pos++; // opening "
        StringBuffer sb = new StringBuffer();
        while (true) {
            char c = s.charAt(pos);
            if (c == '"') {
                pos++;
                break;
            } else if (c == '\\') {
                pos++;
                char esc = s.charAt(pos);
                switch (esc) {
                    case '"': sb.append('"'); break;
                    case '\\': sb.append('\\'); break;
                    case '/': sb.append('/'); break;
                    case 'n': sb.append('\n'); break;
                    case 'r': sb.append('\r'); break;
                    case 't': sb.append('\t'); break;
                    case 'b': sb.append('\b'); break;
                    case 'f': sb.append('\f'); break;
                    case 'u':
                        String hex = s.substring(pos + 1, pos + 5);
                        sb.append((char) Integer.parseInt(hex, 16));
                        pos += 4;
                        break;
                    default:
                        sb.append(esc);
                }
                pos++;
            } else {
                sb.append(c);
                pos++;
            }
        }
        return sb.toString();
    }

    private Long parseNumber() {
        int start = pos;
        if (s.charAt(pos) == '-') {
            pos++;
        }
        while (pos < s.length() && Character.isDigit(s.charAt(pos))) {
            pos++;
        }
        return new Long(Long.parseLong(s.substring(start, pos)));
    }

    private Boolean parseBoolean() {
        if (s.charAt(pos) == 't') {
            pos += 4; // true
            return new Boolean(true);
        } else {
            pos += 5; // false
            return new Boolean(false);
        }
    }

    private Object parseNull() {
        pos += 4; // null
        return NULL;
    }
}
