import React from "react";

/**
 * Simple Prev/Next pagination bar with a page indicator. Used by both the
 * Agent view and Dispatcher table wherever a list could grow large enough
 * to need paging (client-side — pages the already-fetched/filtered list,
 * not a separate server request per page).
 */
export default function Pagination({ currentPage, totalPages, onPageChange, totalItems, pageSize }) {
  if (totalPages <= 1) return null;

  const startItem = (currentPage - 1) * pageSize + 1;
  const endItem = Math.min(currentPage * pageSize, totalItems);

  return (
    <div className="pagination-bar">
      <button
        className="btn"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
      >
        Previous
      </button>

      <span>
        {startItem}-{endItem} of {totalItems} · Page {currentPage} of {totalPages}
      </span>

      <button
        className="btn"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
      >
        Next
      </button>
    </div>
  );
}
