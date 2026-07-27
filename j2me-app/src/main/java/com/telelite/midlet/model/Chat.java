package com.telelite.midlet.model;

public class Chat {

    public final long chatId;
    public final String name;
    public final int unreadCount;

    public Chat(long chatId, String name, int unreadCount) {
        this.chatId = chatId;
        this.name = name;
        this.unreadCount = unreadCount;
    }
}
