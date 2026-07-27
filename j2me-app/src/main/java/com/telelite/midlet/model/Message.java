package com.telelite.midlet.model;

public class Message {

    public final long id;
    public final boolean out;
    public final String text;

    public Message(long id, boolean out, String text) {
        this.id = id;
        this.out = out;
        this.text = text;
    }
}
