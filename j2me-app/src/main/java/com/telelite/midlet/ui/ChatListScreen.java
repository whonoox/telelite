package com.telelite.midlet.ui;

import java.util.Hashtable;
import java.util.Vector;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.List;

import com.telelite.midlet.TeleLiteMIDlet;
import com.telelite.midlet.json.Json;
import com.telelite.midlet.model.Chat;
import com.telelite.midlet.net.ApiClient;
import com.telelite.midlet.net.ApiException;
import com.telelite.midlet.net.ApiResponse;

public class ChatListScreen extends List implements CommandListener {

    private final TeleLiteMIDlet midlet;
    private final String token;
    private Vector chats = new Vector();
    private final Command logoutCommand;

    public ChatListScreen(TeleLiteMIDlet midlet, String token) {
        super("TeleLite", List.IMPLICIT);
        this.midlet = midlet;
        this.token = token;

        logoutCommand = new Command("Logout", Command.SCREEN, 1);
        addCommand(logoutCommand);
        setCommandListener(this);

        append("Loading...", null);
        new Thread(new Runnable() {
            public void run() {
                fetchChats();
            }
        }).start();
    }

    private void fetchChats() {
        try {
            ApiResponse resp = ApiClient.get("/chats", token);
            if (resp.status == 401) {
                midlet.onSessionExpired();
                return;
            }
            Hashtable json = (Hashtable) Json.parse(resp.body);
            Object chatsObj = json.get("chats");
            if (chatsObj != null) {
                Vector rawChats = (Vector) chatsObj;
                Vector parsed = new Vector();
                for (int i = 0; i < rawChats.size(); i++) {
                    Hashtable c = (Hashtable) rawChats.elementAt(i);
                    long chatId = ((Long) c.get("chat_id")).longValue();
                    String name = (String) c.get("name");
                    int unread = (int) ((Long) c.get("unread_count")).longValue();
                    parsed.addElement(new Chat(chatId, name, unread));
                }
                populate(parsed);
            } else {
                populateError(Alerts.errorMessage(json));
            }
        } catch (ApiException e) {
            populateError("Network error, please try again.");
        } catch (Exception e) {
            populateError("Unexpected error.");
        }
    }

    private void populate(Vector parsed) {
        chats = parsed;
        deleteAll();
        if (parsed.size() == 0) {
            append("No chats", null);
            return;
        }
        for (int i = 0; i < parsed.size(); i++) {
            Chat chat = (Chat) parsed.elementAt(i);
            String label = (chat.unreadCount > 0) ? chat.name + " (" + chat.unreadCount + ")" : chat.name;
            append(label, null);
        }
    }

    private void populateError(String message) {
        deleteAll();
        append(message, null);
    }

    public void commandAction(Command c, Displayable d) {
        if (c == logoutCommand) {
            doLogout();
        } else if (c == List.SELECT_COMMAND) {
            int index = getSelectedIndex();
            if (index >= 0 && index < chats.size()) {
                Chat chat = (Chat) chats.elementAt(index);
                midlet.showConversation(token, chat);
            }
        }
    }

    private void doLogout() {
        new Thread(new Runnable() {
            public void run() {
                try {
                    ApiClient.post("/logout", null, token);
                } catch (Exception ignored) {
                    // best-effort revoke; local token is cleared regardless
                }
                midlet.onLogout();
            }
        }).start();
    }
}
