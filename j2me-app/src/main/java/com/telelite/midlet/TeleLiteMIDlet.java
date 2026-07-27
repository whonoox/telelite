package com.telelite.midlet;

import javax.microedition.lcdui.Display;
import javax.microedition.midlet.MIDlet;

import com.telelite.midlet.model.Chat;
import com.telelite.midlet.storage.TokenStore;
import com.telelite.midlet.ui.ChatListScreen;
import com.telelite.midlet.ui.ConversationScreen;
import com.telelite.midlet.ui.LoginCodeScreen;
import com.telelite.midlet.ui.LoginPhoneScreen;

public class TeleLiteMIDlet extends MIDlet {

    private Display display;

    protected void startApp() {
        display = Display.getDisplay(this);
        String token = TokenStore.loadToken();
        if (token != null) {
            showChatList(token);
        } else {
            showLoginPhone();
        }
    }

    protected void pauseApp() {
    }

    protected void destroyApp(boolean unconditional) {
    }

    public Display getDisplay() {
        return display;
    }

    public void showLoginPhone() {
        display.setCurrent(new LoginPhoneScreen(this));
    }

    public void showLoginCode(String pendingId, String phoneNumber, String errorMessage, boolean needsPassword) {
        display.setCurrent(new LoginCodeScreen(this, pendingId, phoneNumber, errorMessage, needsPassword));
    }

    public void onLoginSuccess(String token) {
        TokenStore.saveToken(token);
        showChatList(token);
    }

    public void showChatList(String token) {
        display.setCurrent(new ChatListScreen(this, token));
    }

    public void showConversation(String token, Chat chat) {
        display.setCurrent(new ConversationScreen(this, token, chat));
    }

    public void onLogout() {
        TokenStore.clearToken();
        showLoginPhone();
    }

    public void onSessionExpired() {
        TokenStore.clearToken();
        showLoginPhone();
    }
}
