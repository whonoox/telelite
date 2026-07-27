package com.telelite.midlet;

import java.util.Hashtable;
import javax.microedition.lcdui.Alert;
import javax.microedition.lcdui.AlertType;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Display;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Form;
import javax.microedition.lcdui.TextField;
import javax.microedition.midlet.MIDlet;

import com.telelite.midlet.json.Json;
import com.telelite.midlet.json.JsonBuilder;
import com.telelite.midlet.net.ApiClient;
import com.telelite.midlet.net.ApiException;
import com.telelite.midlet.net.ApiResponse;

public class TeleLiteMIDlet extends MIDlet implements CommandListener {

    private Display display;
    private Command sendCommand;
    private Form phoneForm;
    private TextField phoneField;

    protected void startApp() {
        display = Display.getDisplay(this);
        sendCommand = new Command("Send", Command.OK, 1);

        phoneForm = new Form("TeleLite Login");
        phoneField = new TextField("Phone number", "", 20, TextField.PHONENUMBER);
        phoneForm.append(phoneField);
        phoneForm.addCommand(sendCommand);
        phoneForm.setCommandListener(this);

        display.setCurrent(phoneForm);
    }

    protected void pauseApp() {
    }

    protected void destroyApp(boolean unconditional) {
    }

    public void commandAction(Command c, Displayable d) {
        if (c == sendCommand) {
            final String phoneNumber = phoneField.getString();
            new Thread(new Runnable() {
                public void run() {
                    doLoginRequest(phoneNumber);
                }
            }).start();
        }
    }

    private void doLoginRequest(String phoneNumber) {
        String body = new JsonBuilder().put("phone_number", phoneNumber).build();
        String message;
        try {
            ApiResponse resp = ApiClient.post("/login/request", body, null);
            Hashtable json = (Hashtable) Json.parse(resp.body);
            Object pendingId = json.get("pending_id");
            if (pendingId != null) {
                message = "pending_id: " + pendingId;
            } else {
                Object error = json.get("error");
                Object msg = json.get("message");
                message = "Error: " + error + (msg != null ? " (" + msg + ")" : "");
            }
        } catch (ApiException e) {
            message = "Network error: " + e.getMessage();
        } catch (Exception e) {
            message = "Parse error: " + e;
        }
        showResult(message);
    }

    private void showResult(final String message) {
        final Alert alert = new Alert("Result", message, null, AlertType.INFO);
        alert.setTimeout(Alert.FOREVER);
        display.setCurrent(alert, phoneForm);
    }
}
