package com.telelite.midlet.net;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.util.Vector;
import javax.microedition.lcdui.Image;

public final class AvatarFetcher {

    private AvatarFetcher() {
    }

    /**
     * Fetches PNG avatar thumbnails for the given chat ids in a single HTTP
     * round trip (see /chats/avatars on the backend) instead of one request
     * per chat -- over a feature phone's connection, up to 50 separate
     * requests just to open the chat list would be rough. Returns an array
     * the same length as chatIds; an entry is null if that chat has no
     * photo, the fetch failed, or that one image failed to decode. Only
     * throws for a failure affecting the whole batch (network/parse), never
     * for a single bad image.
     */
    public static Image[] fetchBatch(Vector chatIds, String token) throws ApiException {
        Image[] images = new Image[chatIds.size()];
        if (chatIds.size() == 0) {
            return images;
        }

        StringBuffer idsParam = new StringBuffer();
        for (int i = 0; i < chatIds.size(); i++) {
            if (i > 0) {
                idsParam.append(',');
            }
            idsParam.append(chatIds.elementAt(i));
        }

        RawResponse resp = ApiClient.getRaw("/chats/avatars?fmt=png&ids=" + idsParam, token);
        if (resp.status != 200) {
            return images; // best-effort: chat list stays usable without icons
        }

        try {
            DataInputStream in = new DataInputStream(new ByteArrayInputStream(resp.body));
            for (int i = 0; i < images.length; i++) {
                int flag = in.readUnsignedByte();
                if (flag == 0) {
                    continue;
                }
                int length = in.readInt();
                byte[] png = new byte[length];
                in.readFully(png);
                try {
                    images[i] = Image.createImage(png, 0, length);
                } catch (IllegalArgumentException decodeError) {
                    images[i] = null; // corrupt/unsupported image -- skip icon for this one chat
                }
            }
        } catch (IOException truncatedOrMalformed) {
            // Fall back to whatever was parsed before the batch broke.
        }
        return images;
    }
}
