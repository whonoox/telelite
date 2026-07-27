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

public class LoginCodeScreen extends Form implements CommandListener {

    private final TeleLiteMIDlet midlet;
    private final String pendingId;
    private final String phoneNumber;
    private final boolean needsPassword;
    private final TextField codeField;
    private TextField passwordField;
    private final Command backCommand;
    private final Command verifyCommand;
    private StringItem statusItem;

    public LoginCodeScreen(TeleLiteMIDlet midlet, String pendingId, String phoneNumber,
                           String errorMessage, boolean needsPassword) {
        super("Enter code");
        this.midlet = midlet;
        this.pendingId = pendingId;
        this.phoneNumber = phoneNumber;
        this.needsPassword = needsPassword;

        if (errorMessage != null) {
            append(new StringItem(null, errorMessage));
        }

        codeField = new TextField("Login code", "", 10, TextField.NUMERIC);
        append(codeField);

        if (needsPassword) {
            passwordField = new TextField("2FA password", "", 64, TextField.PASSWORD);
            append(passwordField);
        }

        backCommand = new Command("Back", Command.BACK, 1);
        verifyCommand = new Command("Verify", Command.OK, 1);
        addCommand(backCommand);
        addCommand(verifyCommand);
        setCommandListener(this);
    }

    public void commandAction(Command c, Displayable d) {
        if (c == backCommand) {
            midlet.showLoginPhone();
        } else if (c == verifyCommand) {
            final String code = codeField.getString();
            final String password = (passwordField != null) ? passwordField.getString() : null;
            if (code.length() == 0) {
                return;
            }
            setStatus("Verifying...");
            new Thread(new Runnable() {
                public void run() {
                    doVerify(code, password);
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

    private void doVerify(String code, String password) {
        JsonBuilder builder = new JsonBuilder().put("pending_id", pendingId).put("code", code);
        if (password != null && password.length() > 0) {
            builder.put("password", password);
        }
        String body = builder.build();
        try {
            ApiResponse resp = ApiClient.post("/login/verify", body, null);
            Hashtable json = (Hashtable) Json.parse(resp.body);
            Object token = json.get("token");
            if (token != null) {
                midlet.onLoginSuccess((String) token);
            } else {
                Object error = json.get("error");
                if ("needs_password".equals(error)) {
                    midlet.showLoginCode(pendingId, phoneNumber, "Enter your 2FA password", true);
                } else {
                    midlet.showLoginCode(pendingId, phoneNumber, Alerts.errorMessage(json), needsPassword);
                }
            }
        } catch (ApiException e) {
            midlet.showLoginCode(pendingId, phoneNumber, "Network error, please try again.", needsPassword);
        } catch (Exception e) {
            midlet.showLoginCode(pendingId, phoneNumber, "Unexpected error.", needsPassword);
        }
    }
}
