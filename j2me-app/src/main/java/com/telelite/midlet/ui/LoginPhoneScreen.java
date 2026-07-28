package com.telelite.midlet.ui;

import java.util.Hashtable;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Form;
import javax.microedition.lcdui.StringItem;
import javax.microedition.lcdui.TextField;

import com.telelite.midlet.TeleLiteMIDlet;
import com.telelite.midlet.json.Json;
import com.telelite.midlet.json.JsonBuilder;
import com.telelite.midlet.net.ApiClient;
import com.telelite.midlet.net.ApiException;
import com.telelite.midlet.net.ApiResponse;

public class LoginPhoneScreen extends Form implements CommandListener {

    private final TeleLiteMIDlet midlet;
    private final TextField phoneField;
    private final Command sendCommand;
    private StringItem statusItem;

    public LoginPhoneScreen(TeleLiteMIDlet midlet) {
        this(midlet, null);
    }

    public LoginPhoneScreen(TeleLiteMIDlet midlet, String message) {
        super("TeleLite Login");
        this.midlet = midlet;

        if (message != null) {
            append(new StringItem(null, message));
        }

        phoneField = new TextField("Phone number", "", 20, TextField.PHONENUMBER);
        append(phoneField);

        sendCommand = new Command("Send", Command.OK, 1);
        addCommand(sendCommand);
        setCommandListener(this);
    }

    public void commandAction(Command c, Displayable d) {
        if (c == sendCommand) {
            final String phoneNumber = phoneField.getString();
            if (phoneNumber.length() == 0) {
                return;
            }
            setStatus("Sending...");
            new Thread(new Runnable() {
                public void run() {
                    doLoginRequest(phoneNumber);
                }
            }).start();
        }
    }

    private void setStatus(String s) {
        if (statusItem == null) {
            statusItem = new StringItem(null, s);
            append(statusItem);
        } else {
            statusItem.setText(s);
        }
    }

    private void doLoginRequest(String phoneNumber) {
        String body = new JsonBuilder().put("phone_number", phoneNumber).build();
        try {
            ApiResponse resp = ApiClient.post("/login/request", body, null);
            Hashtable json = (Hashtable) Json.parse(resp.body);
            Object pendingId = json.get("pending_id");
            if (pendingId != null) {
                midlet.showLoginCode((String) pendingId, phoneNumber, null, false);
            } else {
                setStatus(Alerts.errorMessage(json));
            }
        } catch (ApiException e) {
            setStatus("Network error, please try again.");
        } catch (Exception e) {
            setStatus("Unexpected error.");
        }
    }
}
