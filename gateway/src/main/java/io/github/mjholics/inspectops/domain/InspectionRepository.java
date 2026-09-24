package io.github.mjholics.inspectops.domain;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;
import java.util.UUID;

public interface InspectionRepository extends JpaRepository<Inspection, UUID> {

    Page<Inspection> findByStatusOrderByCreatedAtAsc(InspectionStatus status, Pageable pageable);

    /** 라인·상태별 건수 — 운영 대시보드용 집계. */
    @Query("""
            select new io.github.mjholics.inspectops.domain.LineStatusCount(i.lineId, i.status, count(i))
            from Inspection i
            group by i.lineId, i.status
            order by i.lineId, i.status
            """)
    List<LineStatusCount> countByLineAndStatus();
}
