package com.example.contentlab.entity;

import java.io.Serializable;
import java.util.Objects;

public class ContentId implements Serializable {

    private Long id;
    private String type;

    public ContentId() {
    }

    public ContentId(Long id, String type) {
        this.id = id;
        this.type = type;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ContentId other)) return false;

        return Objects.equals(id, other.id)
                && Objects.equals(type, other.type);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, type);
    }
}