package com.telelite.midlet.storage;

import javax.microedition.rms.RecordStore;
import javax.microedition.rms.RecordStoreException;

public final class TokenStore {

    private static final String STORE_NAME = "telelite_auth";

    private TokenStore() {
    }

    public static String loadToken() {
        RecordStore rs = null;
        try {
            rs = RecordStore.openRecordStore(STORE_NAME, false);
            if (rs.getNumRecords() == 0) {
                return null;
            }
            return new String(rs.getRecord(1), "UTF-8");
        } catch (Exception e) {
            return null;
        } finally {
            close(rs);
        }
    }

    public static void saveToken(String token) {
        RecordStore rs = null;
        try {
            rs = RecordStore.openRecordStore(STORE_NAME, true);
            byte[] data = token.getBytes("UTF-8");
            if (rs.getNumRecords() == 0) {
                rs.addRecord(data, 0, data.length);
            } else {
                rs.setRecord(1, data, 0, data.length);
            }
        } catch (Exception e) {
            // best-effort; login still succeeds in-memory for this session
        } finally {
            close(rs);
        }
    }

    public static void clearToken() {
        try {
            RecordStore.deleteRecordStore(STORE_NAME);
        } catch (RecordStoreException ignored) {
        }
    }

    private static void close(RecordStore rs) {
        if (rs != null) {
            try {
                rs.closeRecordStore();
            } catch (RecordStoreException ignored) {
            }
        }
    }
}
