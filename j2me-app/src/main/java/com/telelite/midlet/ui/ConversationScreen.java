package com.telelite.midlet.ui;

import java.util.Hashtable;
import java.util.Vector;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Form;
import javax.microedition.lcdui.Item;
import javax.microedition.lcdui.StringItem;
import javax.microedition.lcdui.TextField;

import com.telelite.midlet.TeleLiteMIDlet;
import com.telelite.midlet.json.Json;
import com.telelite.midlet.json.JsonBuilder;
import com.telelite.midlet.model.Chat;
import com.telelite.midlet.model.Message;
import com.telelite.midlet.net.ApiClient;
import com.telelite.midlet.net.ApiException;
import com.telelite.midlet.net.ApiResponse;

public class ConversationScreen extends Form implements CommandListener {

    private static final int PAGE_LIMIT = 20;

    private final TeleLiteMIDlet midlet;
    private final String token;
    private final Chat chat;
    private Vector messages = new Vector();
    private boolean hasMore = false;
    private boolean olderCommandAdded = false;

    private final Command backCommand;
    private final Command sendCommand;
    private final Command olderCommand;
    private TextField replyField;
    private StringItem statusItem;

    public ConversationScreen(TeleLiteMIDlet midlet, String token, Chat chat) {
        super(chat.name);
        this.midlet = midlet;
        this.token = token;
        this.chat = chat;

        backCommand = new Command("Back", Command.BACK, 1);
        sendCommand = new Command("Send", Command.OK, 1);
        olderCommand = new Command("Older", Command.SCREEN, 2);

        addCommand(backCommand);
        if (chat.canReply) {
            addCommand(sendCommand);
        }
        setCommandListener(this);

        loadMessages(null);
    }

    private void loadMessages(final Long beforeId) {
        setStatus("Loading...");
        new Thread(new Runnable() {
            public void run() {
                fetchMessages(beforeId);
            }
        }).start();
    }

    private void fetchMessages(Long beforeId) {
        String path = "/chats/" + chat.chatId + "/messages?limit=" + PAGE_LIMIT
                + (beforeId != null ? "&before_id=" + beforeId : "");
        try {
            ApiResponse resp = ApiClient.get(path, token);
            if (resp.status == 401) {
                midlet.onSessionExpired();
                return;
            }
            Hashtable json = (Hashtable) Json.parse(resp.body);
            Object msgsObj = json.get("messages");
            if (msgsObj != null) {
                Vector rawMsgs = (Vector) msgsObj;
                Vector parsed = new Vector();
                for (int i = 0; i < rawMsgs.size(); i++) {
                    Hashtable m = (Hashtable) rawMsgs.elementAt(i);
                    long id = ((Long) m.get("id")).longValue();
                    boolean out = ((Boolean) m.get("out")).booleanValue();
                    Object textObj = m.get("text");
                    String text = (textObj != null && textObj != Json.NULL) ? (String) textObj : "";
                    parsed.addElement(new Message(id, out, text));
                }
                boolean gotFullPage = parsed.size() == PAGE_LIMIT;
                if (beforeId == null) {
                    messages = parsed;
                } else {
                    Vector combined = new Vector();
                    for (int i = 0; i < parsed.size(); i++) {
                        combined.addElement(parsed.elementAt(i));
                    }
                    for (int i = 0; i < messages.size(); i++) {
                        combined.addElement(messages.elementAt(i));
                    }
                    messages = combined;
                }
                hasMore = gotFullPage;
                render();
            } else {
                setStatus(Alerts.errorMessage(json));
            }
        } catch (ApiException e) {
            setStatus("Network error, please try again.");
        } catch (Exception e) {
            setStatus("Unexpected error.");
        }
    }

    private void render() {
        deleteAll();
        statusItem = null;

        if (hasMore && !olderCommandAdded) {
            addCommand(olderCommand);
            olderCommandAdded = true;
        } else if (!hasMore && olderCommandAdded) {
            removeCommand(olderCommand);
            olderCommandAdded = false;
        }

        if (messages.size() == 0) {
            append(new StringItem(null, "No messages yet"));
        }
        for (int i = 0; i < messages.size(); i++) {
            Message m = (Message) messages.elementAt(i);
            String prefix = m.out ? "Me: " : "";
            StringItem item = new StringItem(null, prefix + m.text);
            item.setLayout(Item.LAYOUT_NEWLINE_BEFORE | Item.LAYOUT_NEWLINE_AFTER);
            append(item);
        }

        if (chat.canReply) {
            if (replyField == null) {
                replyField = new TextField("Reply", "", 500, TextField.ANY);
            }
            append(replyField);
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

    public void commandAction(Command c, Displayable d) {
        if (c == backCommand) {
            midlet.showChatList(token);
        } else if (c == sendCommand && replyField != null) {
            final String text = replyField.getString();
            if (text.length() == 0) {
                return;
            }
            setStatus("Sending...");
            new Thread(new Runnable() {
                public void run() {
                    doSend(text);
                }
            }).start();
        } else if (c == olderCommand) {
            if (messages.size() > 0) {
                Message oldest = (Message) messages.elementAt(0);
                loadMessages(new Long(oldest.id));
            }
        }
    }

    private void doSend(String text) {
        String body = new JsonBuilder().put("text", text).build();
        try {
            ApiResponse resp = ApiClient.post("/chats/" + chat.chatId + "/messages", body, token);
            if (resp.status == 401) {
                midlet.onSessionExpired();
                return;
            }
            Hashtable json = (Hashtable) Json.parse(resp.body);
            Object messageObj = json.get("message");
            if (messageObj != null) {
                replyField.setString("");
                loadMessages(null);
            } else {
                // draft text is preserved since replyField isn't touched here
                setStatus(Alerts.errorMessage(json));
            }
        } catch (ApiException e) {
            setStatus("Network error, please try again.");
        } catch (Exception e) {
            setStatus("Unexpected error.");
        }
    }
}
