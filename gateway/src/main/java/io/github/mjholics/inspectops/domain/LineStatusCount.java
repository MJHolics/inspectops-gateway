package io.github.mjholics.inspectops.domain;

public record LineStatusCount(String lineId, InspectionStatus status, long count) {
}
