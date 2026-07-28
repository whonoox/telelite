package com.telelite.midlet.ui;

import java.util.Hashtable;
import javax.microedition.lcdui.Alert;
import javax.microedition.lcdui.AlertType;
import javax.microedition.lcdui.Display;
import javax.microedition.lcdui.Displayable;

import com.telelite.midlet.json.Json;

public final class Alerts {

    private Alerts() {
    }

    public static void showError(Display display, Displayable back, String message) {
        Alert alert = new Alert("Error", message, null, AlertType.ERROR);
        alert.setTimeout(Alert.FOREVER);
        display.setCurrent(alert, back);
    }

    /** Extracts a human message from an error envelope: {"error", "message"?, "retry_after"?}. */
    public static String errorMessage(Hashtable json) {
        String base;
        Object msg = json.get("message");
        if (msg != null && msg != Json.NULL) {
            base = String.valueOf(msg);
        } else {
            Object err = json.get("error");
            base = err != null ? String.valueOf(err) : "Unknown error";
        }
        Object retryAfter = json.get("retry_after");
        if (retryAfter != null && retryAfter != Json.NULL) {
            base = base + " (retry in " + retryAfter + "s)";
        }
        return base;
    }
}
