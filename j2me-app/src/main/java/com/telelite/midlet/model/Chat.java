package com.telelite.midlet.model;

public class Chat {

    public final long chatId;
    public final String name;
    public final int unreadCount;
    public final boolean canReply;

    public Chat(long chatId, String name, int unreadCount, boolean canReply) {
        this.chatId = chatId;
        this.name = name;
        this.unreadCount = unreadCount;
        this.canReply = canReply;
    }
}
