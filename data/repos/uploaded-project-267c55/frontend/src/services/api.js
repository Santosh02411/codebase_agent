/**
 * Handles all HTTP calls to the FastAPI backend.
 *
 * Most endpoints now require a logged-in user, so every function here
 * takes a `token` (the JWT from AuthContext) and attaches it as a
 * 'Authorization: Bearer <token>' header. Components get this token from
 * `useAuth()` and pass it in.
 */

// Defaults to the local FastAPI dev server so `npm run dev` works with
// zero config, same as always. VITE_API_BASE_URL lets a real build
// (Docker, or any other deployment) point at a different backend URL —
// Vite only inlines `import.meta.env.VITE_*` vars at BUILD time, not
// runtime, so this has to be set when the frontend is built (a
// `--build-arg` in Docker, or a `.env` file Vite reads), not afterwards.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function authHeaders(token) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

export async function createDeliveryOnServer(token, record) {
  const response = await fetch(`${API_BASE_URL}/deliveries/`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(record),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create delivery on server");
  return data;
}

export async function updateDeliveryOnServer(token, id, update) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${id}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(update),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update delivery on server");
  return data;
}

export async function fetchAllDeliveriesFromServer(token) {
  const response = await fetch(`${API_BASE_URL}/deliveries/`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch deliveries from server");
  return data;
}

export async function fetchMyDeliveriesFromServer(token) {
  const response = await fetch(`${API_BASE_URL}/deliveries/mine`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch your deliveries from server");
  return data;
}

export async function deleteDeliveryOnServer(token, id) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete delivery on server");
  return data;
}

export async function fetchAgentsList(token) {
  const response = await fetch(`${API_BASE_URL}/users/agents`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch agents list");
  return data;
}

export async function fetchDeliveryHistory(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/history`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch delivery history");
  return data;
}

export async function fetchDeliveryMessages(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/messages`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch messages");
  return data;
}

export async function sendDeliveryMessage(token, deliveryId, message) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/messages`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ message }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to send message");
  return data;
}

export async function bulkImportDeliveries(token, rows) {
  const response = await fetch(`${API_BASE_URL}/deliveries/bulk-import`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ rows }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Bulk import failed");
  return data;
}

/**
 * Downloads the CSV export and triggers a browser "Save File" prompt.
 *
 * This can't just be a plain <a href="..."> link, because the export
 * endpoint requires an Authorization header — a link click can't attach
 * custom headers. Instead: fetch it manually (with the header), turn the
 * response into a Blob, and programmatically click a temporary <a> tag
 * pointing at an object URL for that blob. This is the standard pattern
 * for downloading an authenticated file from the browser.
 */
export async function exportDeliveriesCSV(token, dateFrom, dateTo) {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);

  const response = await fetch(`${API_BASE_URL}/deliveries/export?${params.toString()}`, {
    headers: authHeaders(token),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Export failed");
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);

  // Extract the filename the server suggested, falling back to a generic one
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename=([^;]+)/);
  const filename = match ? match[1].trim() : "deliveries_export.csv";

  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}

// ---------- Admin ----------

export async function fetchOrganizationUsers(token) {
  const response = await fetch(`${API_BASE_URL}/admin/users`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch organization users");
  return data;
}

export async function fetchOrganizationInfo(token) {
  const response = await fetch(`${API_BASE_URL}/admin/organization`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch organization info");
  return data;
}

export async function fetchPublicTracking(deliveryId) {
  const response = await fetch(`${API_BASE_URL}/track/${deliveryId}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Tracking info not found");
  return data;
}

export async function fetchPublicTrackingAgentLocation(deliveryId) {
  const response = await fetch(`${API_BASE_URL}/track/${deliveryId}/agent-location`);
  if (!response.ok) return null; // 404 just means no live position to show right now — not an error state
  return response.json();
}

export async function submitDeliveryFeedback(deliveryId, rating, comment) {
  const response = await fetch(`${API_BASE_URL}/track/${deliveryId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, comment: comment || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to submit feedback");
  return data;
}

function customerAuthHeaders(token) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

export async function fetchMyCustomerDeliveries(token, { limit, offset } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set("limit", limit);
  if (offset) params.set("offset", offset);
  const response = await fetch(`${API_BASE_URL}/customer/deliveries?${params.toString()}`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch your orders");
  return data;
}

export async function fetchMyCustomerDeliveryHistory(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/history`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch order history");
  return data;
}

export async function fetchMyCustomerDeliveryFeedback(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/feedback`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch feedback");
  return data;
}

export async function fetchMyCustomerNotifications(token, { limit, offset } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set("limit", limit);
  if (offset) params.set("offset", offset);
  const response = await fetch(`${API_BASE_URL}/customer/notifications?${params.toString()}`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch notifications");
  return data;
}

export async function claimCustomerOrder(token, orderId, phone) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/claim`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ order_id: orderId, phone }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to link that order");
  return data;
}

export async function cancelCustomerDelivery(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/cancel`, {
    method: "POST",
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to cancel order");
  return data;
}

export async function reorderCustomerDelivery(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/reorder`, {
    method: "POST",
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to reorder");
  return data;
}

export async function fetchCustomerDeliveryAgentLocation(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/agent-location`, {
    headers: customerAuthHeaders(token),
  });
  if (!response.ok) return null; // 404 just means agent hasn't shared location yet — not an error state
  return response.json();
}

export async function fetchMyCustomerAddresses(token) {
  const response = await fetch(`${API_BASE_URL}/customer/addresses`, {
    headers: customerAuthHeaders(token),
  });
  return response.json();
}

export async function addCustomerAddress(token, address) {
  const response = await fetch(`${API_BASE_URL}/customer/addresses`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify(address),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to save address");
  return data;
}

export async function deleteCustomerAddress(token, addressId) {
  const response = await fetch(`${API_BASE_URL}/customer/addresses/${addressId}`, {
    method: "DELETE",
    headers: customerAuthHeaders(token),
  });
  if (!response.ok) throw new Error("Failed to delete address");
  return response.json();
}

export async function fetchVapidPublicKey(token) {
  const response = await fetch(`${API_BASE_URL}/customer/push/vapid-public-key`, {
    headers: customerAuthHeaders(token),
  });
  return response.json();
}

export async function subscribeToPush(token, subscription) {
  const response = await fetch(`${API_BASE_URL}/customer/push/subscribe`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify(subscription),
  });
  if (!response.ok) throw new Error("Failed to subscribe to push notifications");
  return response.json();
}

export async function updateMyAgentLocation(token, latitude, longitude) {
  const response = await fetch(`${API_BASE_URL}/users/me/location`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify({ latitude, longitude }),
  });
  if (!response.ok) throw new Error("Failed to update location");
  return response.json();
}

// ---------- Storefront / Cart / Checkout ----------

export async function fetchPublicStores() {
  const response = await fetch(`${API_BASE_URL}/stores/`);
  return response.json();
}

export async function fetchStoreProducts(orgId) {
  const response = await fetch(`${API_BASE_URL}/stores/${orgId}/products`);
  return response.json();
}

export async function fetchMyCart(token) {
  const response = await fetch(`${API_BASE_URL}/customer/cart/`, {
    headers: customerAuthHeaders(token),
  });
  return response.json();
}

export async function addToCart(token, productId, quantity = 1) {
  const response = await fetch(`${API_BASE_URL}/customer/cart/`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ product_id: productId, quantity }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to add to cart");
  return data;
}

export async function updateCartItem(token, itemId, quantity) {
  const response = await fetch(`${API_BASE_URL}/customer/cart/${itemId}`, {
    method: "PATCH",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ quantity }),
  });
  return response.json();
}

export async function removeCartItem(token, itemId) {
  const response = await fetch(`${API_BASE_URL}/customer/cart/${itemId}`, {
    method: "DELETE",
    headers: customerAuthHeaders(token),
  });
  return response.json();
}

export async function clearCart(token) {
  const response = await fetch(`${API_BASE_URL}/customer/cart/`, {
    method: "DELETE",
    headers: customerAuthHeaders(token),
  });
  return response.json();
}

export async function checkoutCart(token, addressLine, city, phone, couponCode, slotStart, paymentMethod = "online") {
  const response = await fetch(`${API_BASE_URL}/customer/checkout`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({
      address_line: addressLine,
      city,
      phone,
      coupon_code: couponCode || null,
      slot_start: slotStart || null,
      payment_method: paymentMethod,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Checkout failed");
  return data;
}

export async function fetchDeliverySlots(orgId, dateStr) {
  const response = await fetch(`${API_BASE_URL}/stores/${orgId}/delivery-slots?date=${dateStr}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load delivery slots");
  return data;
}

export async function validateCoupon(token, code) {
  const response = await fetch(`${API_BASE_URL}/customer/checkout/validate-coupon`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ code }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Invalid coupon");
  return data;
}

export async function verifyPayment(token, payload) {
  const response = await fetch(`${API_BASE_URL}/customer/checkout/verify`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Payment verification failed");
  return data;
}

export async function fetchMyOrders(token, { limit, offset, deliveryId } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set("limit", limit);
  if (offset) params.set("offset", offset);
  if (deliveryId) params.set("delivery_id", deliveryId);
  const response = await fetch(`${API_BASE_URL}/customer/orders?${params.toString()}`, {
    headers: customerAuthHeaders(token),
  });
  return response.json();
}

// ---------- Product reviews ----------

export async function fetchProductReviews(productId) {
  const response = await fetch(`${API_BASE_URL}/stores/products/${productId}/reviews`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch reviews");
  return data;
}

export async function fetchReviewableItems(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/reviewable-items`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to fetch reviewable items");
  return data;
}

export async function submitProductReview(token, productId, orderId, rating, comment) {
  const response = await fetch(`${API_BASE_URL}/customer/products/${productId}/reviews`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ order_id: orderId, rating, comment: comment || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to submit review");
  return data;
}

// ---------- Dispatcher: product catalog + unassigned orders ----------

export async function fetchMyProducts(token) {
  const response = await fetch(`${API_BASE_URL}/admin/products/`, {
    headers: authHeaders(token),
  });
  return response.json();
}

export async function uploadProductImage(token, file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE_URL}/admin/products/upload-image`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }, // no Content-Type — the browser sets the multipart boundary itself
    body: formData,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to upload image");
  return data;
}

export async function createProduct(token, product) {
  const response = await fetch(`${API_BASE_URL}/admin/products/`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(product),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create product");
  return data;
}

export async function updateProduct(token, productId, updates) {
  const response = await fetch(`${API_BASE_URL}/admin/products/${productId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(updates),
  });
  return response.json();
}

export async function deleteProduct(token, productId) {
  const response = await fetch(`${API_BASE_URL}/admin/products/${productId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  return response.json();
}

export async function fetchMyOrganization(token) {
  const response = await fetch(`${API_BASE_URL}/admin/organization`, {
    headers: authHeaders(token),
  });
  return response.json();
}

export async function fetchAnalytics(token, days = 30) {
  const response = await fetch(`${API_BASE_URL}/admin/analytics/?days=${days}`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load analytics");
  return data;
}

// ---------- Staff push notifications ----------

export async function fetchStaffVapidPublicKey(token) {
  const response = await fetch(`${API_BASE_URL}/users/me/push/vapid-public-key`, {
    headers: authHeaders(token),
  });
  return response.json();
}

export async function subscribeStaffToPush(token, subscription) {
  const response = await fetch(`${API_BASE_URL}/users/me/push/subscribe`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(subscription),
  });
  if (!response.ok) throw new Error("Failed to subscribe to push notifications");
  return response.json();
}
export async function setStoreVisibility(token, isPublic) {
  const response = await fetch(`${API_BASE_URL}/admin/store/visibility`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ is_public_store: isPublic }),
  });
  return response.json();
}

export async function setStorePricing(token, deliveryFee, taxRatePercent) {
  const response = await fetch(`${API_BASE_URL}/admin/store/pricing`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ delivery_fee: deliveryFee, tax_rate_percent: taxRatePercent }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update pricing");
  return data;
}

export async function setStoreSlotSettings(token, settings) {
  const response = await fetch(`${API_BASE_URL}/admin/store/slot-settings`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(settings),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update slot settings");
  return data;
}

// ---------- Coupons ----------

export async function fetchMyCoupons(token) {
  const response = await fetch(`${API_BASE_URL}/admin/coupons/`, {
    headers: authHeaders(token),
  });
  return response.json();
}

export async function createCoupon(token, coupon) {
  const response = await fetch(`${API_BASE_URL}/admin/coupons/`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(coupon),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create coupon");
  return data;
}

export async function updateCoupon(token, couponId, updates) {
  const response = await fetch(`${API_BASE_URL}/admin/coupons/${couponId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update coupon");
  return data;
}

export async function deleteCoupon(token, couponId) {
  const response = await fetch(`${API_BASE_URL}/admin/coupons/${couponId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  return response.json();
}

export async function fetchUnassignedDeliveries(token) {
  const response = await fetch(`${API_BASE_URL}/deliveries/unassigned`, {
    headers: authHeaders(token),
  });
  return response.json();
}

export async function assignAgentToDelivery(token, deliveryId, agentId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/assign-agent`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ agent_id: agentId }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to assign agent");
  return data;
}

export async function returnDeliveryToPool(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/return-to-pool`, {
    method: "PATCH",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to return delivery to pool");
  return data;
}

export async function bulkUpdateDeliveryStatus(token, deliveryIds, status) {
  const response = await fetch(`${API_BASE_URL}/deliveries/bulk-status`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ delivery_ids: deliveryIds, status }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Bulk status update failed");
  return data; // { results, success_count, failure_count }
}

export async function bulkAssignAgent(token, deliveryIds, agentId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/bulk-assign-agent`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ delivery_ids: deliveryIds, agent_id: agentId }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Bulk reassign failed");
  return data; // { results, success_count, failure_count }
}

export async function fetchSuggestedAgents(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/suggested-agents`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load agent suggestions");
  return data;
}

export async function optimizeRouteOnServer(token, deliveryIds, startLatitude, startLongitude) {
  const response = await fetch(`${API_BASE_URL}/deliveries/optimize-route`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      delivery_ids: deliveryIds,
      start_latitude: startLatitude ?? null,
      start_longitude: startLongitude ?? null,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to optimize route");
  return data; // { ordered_delivery_ids, used_real_routing }
}

export async function autoAssignDelivery(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/auto-assign`, {
    method: "POST",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to auto-assign");
  return data;
}

export async function markAllCustomerNotificationsRead(token) {
  const response = await fetch(`${API_BASE_URL}/customer/notifications/mark-all-read`, {
    method: "POST",
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to mark notifications read");
  return data;
}

export async function deleteCustomerNotification(token, notificationId) {
  const response = await fetch(`${API_BASE_URL}/customer/notifications/${notificationId}`, {
    method: "DELETE",
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete notification");
  return data;
}

export async function clearCustomerNotifications(token, onlyRead = true) {
  const response = await fetch(`${API_BASE_URL}/customer/notifications?only_read=${onlyRead}`, {
    method: "DELETE",
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to clear notifications");
  return data;
}

export async function fetchMyCustomerProfile(token) {
  const response = await fetch(`${API_BASE_URL}/customer/me`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load your profile");
  return data;
}

export async function updateMyCustomerProfile(token, updates) {
  const response = await fetch(`${API_BASE_URL}/customer/me`, {
    method: "PATCH",
    headers: customerAuthHeaders(token),
    body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update your profile");
  return data;
}

export async function changeMyCustomerPassword(token, currentPassword, newPassword) {
  const response = await fetch(`${API_BASE_URL}/customer/me/change-password`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to change your password");
  return data;
}

export async function setMyCustomerPassword(token, newPassword) {
  const response = await fetch(`${API_BASE_URL}/customer/me/set-password`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ new_password: newPassword }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to set a password");
  return data;
}

// ---------- Staff self-service account settings (mirrors the customer equivalents above) ----------

export async function fetchMyStaffProfile(token) {
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load your profile");
  return data;
}

export async function updateMyStaffProfile(token, updates) {
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update your profile");
  return data;
}

export async function changeMyStaffPassword(token, currentPassword, newPassword) {
  const response = await fetch(`${API_BASE_URL}/auth/me/change-password`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to change your password");
  return data;
}

export async function setMyStaffPassword(token, newPassword) {
  const response = await fetch(`${API_BASE_URL}/auth/me/set-password`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ new_password: newPassword }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to set a password");
  return data;
}

export async function deactivateUser(token, userId) {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/deactivate`, {
    method: "PATCH",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to deactivate user");
  return data;
}

export async function activateUser(token, userId) {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/activate`, {
    method: "PATCH",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to activate user");
  return data;
}

export async function resetUserPassword(token, userId, newPassword) {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/reset-password`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ new_password: newPassword }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to reset password");
  return data;
}

// ---------- Two-factor authentication (staff) ----------

export async function fetchTwoFactorStatus(token) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/status`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load two-factor status");
  return data; // { totp_enabled }
}

export async function setupTwoFactor(token) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/setup`, {
    method: "POST",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to start two-factor setup");
  return data; // { secret, otpauth_uri }
}

export async function enableTwoFactor(token, code) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/enable`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ code }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to enable two-factor authentication");
  return data;
}

export async function disableTwoFactor(token, password) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/disable`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ password }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to disable two-factor authentication");
  return data;
}

// ---------- Admin audit log ----------

export async function fetchAuditLog(token, { dateFrom, dateTo, changedByUserId, orderId, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (changedByUserId) params.set("changed_by_user_id", changedByUserId);
  if (orderId) params.set("order_id", orderId);
  if (limit) params.set("limit", limit);
  if (offset) params.set("offset", offset);

  const response = await fetch(`${API_BASE_URL}/admin/audit-log?${params.toString()}`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load audit log");
  return data;
}

// ---------- General admin action log (users/products/coupons/store settings) ----------

export async function fetchActionLog(token, { action, entityType, actorUserId, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (action) params.set("action", action);
  if (entityType) params.set("entity_type", entityType);
  if (actorUserId) params.set("actor_user_id", actorUserId);
  if (limit) params.set("limit", limit);
  if (offset) params.set("offset", offset);

  const response = await fetch(`${API_BASE_URL}/admin/action-log?${params.toString()}`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load action log");
  return data;
}

// ---------- Delivery zones/territories ----------

export async function fetchZones(token) {
  const response = await fetch(`${API_BASE_URL}/admin/zones/`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load zones");
  return data;
}

export async function createZone(token, zone) {
  const response = await fetch(`${API_BASE_URL}/admin/zones/`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(zone),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create zone");
  return data;
}

export async function updateZone(token, zoneId, updates) {
  const response = await fetch(`${API_BASE_URL}/admin/zones/${zoneId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update zone");
  return data;
}

export async function deleteZone(token, zoneId) {
  const response = await fetch(`${API_BASE_URL}/admin/zones/${zoneId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete zone");
  return data;
}

export async function assignAgentToZone(token, zoneId, agentId) {
  const response = await fetch(`${API_BASE_URL}/admin/zones/${zoneId}/agents/${agentId}`, {
    method: "POST",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to assign agent to zone");
  return data;
}

export async function unassignAgentFromZone(token, zoneId, agentId) {
  const response = await fetch(`${API_BASE_URL}/admin/zones/${zoneId}/agents/${agentId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to remove agent from zone");
  return data;
}

// ---------- Returns / exchanges ----------

export async function createReturnRequest(token, deliveryId, requestType, reason) {
  const response = await fetch(`${API_BASE_URL}/customer/return-requests/`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify({ delivery_id: deliveryId, request_type: requestType, reason }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to submit request");
  return data;
}

export async function fetchMyReturnRequests(token) {
  const response = await fetch(`${API_BASE_URL}/customer/return-requests/`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load return requests");
  return data;
}

export async function fetchReturnRequests(token, statusFilter) {
  const params = statusFilter ? `?status=${statusFilter}` : "";
  const response = await fetch(`${API_BASE_URL}/admin/return-requests/${params}`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load return requests");
  return data;
}

export async function approveReturnRequest(token, requestId, resolutionNote) {
  const response = await fetch(`${API_BASE_URL}/admin/return-requests/${requestId}/approve`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ resolution_note: resolutionNote || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to approve request");
  return data;
}

export async function rejectReturnRequest(token, requestId, resolutionNote) {
  const response = await fetch(`${API_BASE_URL}/admin/return-requests/${requestId}/reject`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ resolution_note: resolutionNote || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to reject request");
  return data;
}

// ---------- Customer data privacy (GDPR export / delete) ----------

export async function exportCustomerData(token) {
  const response = await fetch(`${API_BASE_URL}/customer/data-export`, {
    headers: authHeaders(token),
  });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || "Failed to export your data");
  }
  return response.blob();
}

export async function deleteCustomerAccount(token, password) {
  const response = await fetch(`${API_BASE_URL}/customer/account`, {
    method: "DELETE",
    headers: authHeaders(token),
    body: JSON.stringify({ password }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete your account");
  return data;
}

// ---------- Agent coverage area (real GPS + reverse geocoding) ----------

export async function detectMyArea(token, latitude, longitude) {
  const response = await fetch(`${API_BASE_URL}/users/me/area/detect`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ latitude, longitude }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to detect your area");
  return data; // { area_name, area_latitude, area_longitude }
}

export async function clearMyArea(token) {
  const response = await fetch(`${API_BASE_URL}/users/me/area`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to clear your area");
  return data;
}

export async function setMyArea(token, areaName) {
  const response = await fetch(`${API_BASE_URL}/users/me/area/set`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ area_name: areaName }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to set your area");
  return data;
}

export async function fetchAreaSuggestions(token) {
  const response = await fetch(`${API_BASE_URL}/users/me/area/suggestions`, {
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load area suggestions");
  return data; // string[]
}

// ---------- Two-factor authentication: email-code method ----------

export async function setupEmailTwoFactor(token) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/setup-email`, {
    method: "POST",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to send a confirmation code");
  return data; // { sent, masked_email }
}

export async function enableEmailTwoFactor(token, code) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/enable-email`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ code }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to enable two-factor authentication");
  return data;
}

export async function resendTwoFactorLoginCode(challengeToken) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/resend-code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ challenge_token: challengeToken, code: "" }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to resend the code");
  return data; // { sent, masked_email }
}

/**
 * Sends a batch of pending records to the server's /sync endpoint.
 * NOTE: this endpoint is intentionally left unauthenticated for now — see
 * docs/SECURITY_AND_ACCESS.md for why, and what a production version would
 * add here.
 */
export async function syncPendingDeliveries(pendingRecords) {
  const response = await fetch(`${API_BASE_URL}/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ records: pendingRecords }),
  });
  if (!response.ok) throw new Error("Sync request failed");
  return response.json();
}

// ---------- Marketplace search (stores) ----------

export async function fetchPublicStoresFiltered(search, category) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (category) params.set("category", category);
  const qs = params.toString();
  const response = await fetch(`${API_BASE_URL}/stores/${qs ? `?${qs}` : ""}`);
  return response.json();
}

export async function fetchStoreCategories() {
  const response = await fetch(`${API_BASE_URL}/stores/categories`);
  return response.json();
}

export async function setStoreProfile(token, category, description) {
  const response = await fetch(`${API_BASE_URL}/admin/store/profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ category: category || null, description: description || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update store profile");
  return data;
}

// ---------- Recurring / subscription orders ----------

export async function fetchMySubscriptions(token) {
  const response = await fetch(`${API_BASE_URL}/customer/subscriptions/`, {
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load subscriptions");
  return data;
}

export async function createSubscription(token, payload) {
  const response = await fetch(`${API_BASE_URL}/customer/subscriptions/`, {
    method: "POST",
    headers: customerAuthHeaders(token),
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create subscription");
  return data;
}

export async function updateSubscription(token, subscriptionId, payload) {
  const response = await fetch(`${API_BASE_URL}/customer/subscriptions/${subscriptionId}`, {
    method: "PATCH",
    headers: customerAuthHeaders(token),
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update subscription");
  return data;
}

async function _subscriptionAction(token, subscriptionId, action) {
  const response = await fetch(`${API_BASE_URL}/customer/subscriptions/${subscriptionId}/${action}`, {
    method: "POST",
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `Failed to ${action} subscription`);
  return data;
}

export const pauseSubscription = (token, id) => _subscriptionAction(token, id, "pause");
export const resumeSubscription = (token, id) => _subscriptionAction(token, id, "resume");
export const cancelSubscription = (token, id) => _subscriptionAction(token, id, "cancel");
export const runSubscriptionNow = (token, id) => _subscriptionAction(token, id, "run-now");

export async function initiateSubscriptionOrderPayment(token, orderId) {
  const response = await fetch(`${API_BASE_URL}/customer/subscriptions/orders/${orderId}/initiate-payment`, {
    method: "POST",
    headers: customerAuthHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to start payment");
  return data;
}

// ---------- Failed-delivery reason codes ----------

export async function fetchFailedDeliveryReasons(token) {
  const response = await fetch(`${API_BASE_URL}/admin/failed-delivery-reasons/`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load reason codes");
  return data;
}

export async function fetchActiveFailedDeliveryReasons(token) {
  const response = await fetch(`${API_BASE_URL}/deliveries/reason-codes/active`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load reason codes");
  return data;
}

export async function createFailedDeliveryReason(token, reason) {
  const response = await fetch(`${API_BASE_URL}/admin/failed-delivery-reasons/`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(reason),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create reason code");
  return data;
}

export async function updateFailedDeliveryReason(token, reasonId, updates) {
  const response = await fetch(`${API_BASE_URL}/admin/failed-delivery-reasons/${reasonId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update reason code");
  return data;
}

export async function deleteFailedDeliveryReason(token, reasonId) {
  const response = await fetch(`${API_BASE_URL}/admin/failed-delivery-reasons/${reasonId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete reason code");
  return data;
}

// ---------- Delivery attempts / reschedule / priority ----------

export async function fetchDeliveryAttempts(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/attempts`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load delivery attempts");
  return data;
}

export async function rescheduleDelivery(token, deliveryId, rescheduledTo, reason) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/reschedule`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ rescheduled_to: rescheduledTo, reason }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to reschedule delivery");
  return data;
}

export async function updateDeliveryPriority(token, deliveryId, priority) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/priority`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ priority }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update priority");
  return data;
}

// ---------- Workforce: shifts ----------

export async function createShift(token, shift) {
  const response = await fetch(`${API_BASE_URL}/workforce/shifts`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(shift),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create shift");
  return data;
}

export async function fetchShifts(token, { userId, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const response = await fetch(`${API_BASE_URL}/workforce/shifts?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load shifts");
  return data;
}

export async function fetchMyShifts(token, { dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const response = await fetch(`${API_BASE_URL}/workforce/shifts/mine?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load your shifts");
  return data;
}

export async function updateShift(token, shiftId, updates) {
  const response = await fetch(`${API_BASE_URL}/workforce/shifts/${shiftId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update shift");
  return data;
}

export async function deleteShift(token, shiftId) {
  const response = await fetch(`${API_BASE_URL}/workforce/shifts/${shiftId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete shift");
  return data;
}

// ---------- Workforce: attendance ----------

export async function clockIn(token, shiftId, note) {
  const response = await fetch(`${API_BASE_URL}/workforce/attendance/clock-in`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ shift_id: shiftId || null, note: note || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to clock in");
  return data;
}

export async function clockOut(token, note) {
  const response = await fetch(`${API_BASE_URL}/workforce/attendance/clock-out`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ note: note || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to clock out");
  return data;
}

export async function fetchMyAttendance(token) {
  const response = await fetch(`${API_BASE_URL}/workforce/attendance/mine`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load attendance");
  return data;
}

export async function fetchAttendance(token, { userId, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const response = await fetch(`${API_BASE_URL}/workforce/attendance?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load attendance");
  return data;
}

// ---------- Workforce: leave requests ----------

export async function createLeaveRequest(token, request) {
  const response = await fetch(`${API_BASE_URL}/workforce/leave-requests`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(request),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to submit leave request");
  return data;
}

export async function fetchMyLeaveRequests(token) {
  const response = await fetch(`${API_BASE_URL}/workforce/leave-requests/mine`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load leave requests");
  return data;
}

export async function cancelLeaveRequest(token, requestId) {
  const response = await fetch(`${API_BASE_URL}/workforce/leave-requests/${requestId}/cancel`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to cancel leave request");
  return data;
}

export async function fetchLeaveRequests(token, { status, userId } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (userId) params.set("user_id", userId);
  const response = await fetch(`${API_BASE_URL}/workforce/leave-requests?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load leave requests");
  return data;
}

export async function approveLeaveRequest(token, requestId, reviewNote) {
  const response = await fetch(`${API_BASE_URL}/workforce/leave-requests/${requestId}/approve`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ review_note: reviewNote || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to approve leave request");
  return data;
}

export async function rejectLeaveRequest(token, requestId, reviewNote) {
  const response = await fetch(`${API_BASE_URL}/workforce/leave-requests/${requestId}/reject`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ review_note: reviewNote || null }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to reject leave request");
  return data;
}

// ---------- Workforce: pay rates + earnings ----------

export async function setPayRate(token, userId, updates) {
  const response = await fetch(`${API_BASE_URL}/workforce/pay-rate/${userId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update pay rate");
  return data;
}

export async function generateEarnings(token, { userId, periodStart, periodEnd }) {
  const response = await fetch(`${API_BASE_URL}/workforce/earnings/generate`, {
    method: "POST", headers: authHeaders(token),
    body: JSON.stringify({ user_id: userId || null, period_start: periodStart, period_end: periodEnd }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to generate earnings");
  return data;
}

export async function fetchMyEarnings(token) {
  const response = await fetch(`${API_BASE_URL}/workforce/earnings/mine`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load earnings");
  return data;
}

export async function fetchEarnings(token, { userId, status } = {}) {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  if (status) params.set("status", status);
  const response = await fetch(`${API_BASE_URL}/workforce/earnings?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load earnings");
  return data;
}

export async function finalizeEarnings(token, statementId) {
  const response = await fetch(`${API_BASE_URL}/workforce/earnings/${statementId}/finalize`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to finalize statement");
  return data;
}

export async function markEarningsPaid(token, statementId) {
  const response = await fetch(`${API_BASE_URL}/workforce/earnings/${statementId}/mark-paid`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to mark statement paid");
  return data;
}

// ---------- Proof of Delivery (Phase 1) ----------

export async function generateDeliveryOtp(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/pod/otp`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to send verification code");
  return data;
}

export async function submitProofOfDelivery(token, deliveryId, payload) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/pod`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to submit proof of delivery");
  return data;
}

export async function fetchProofOfDelivery(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/pod`, { headers: authHeaders(token) });
  if (response.status === 404) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load proof of delivery");
  return data;
}

export async function fetchProofOfDeliveryHistory(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/pod/history`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load proof of delivery history");
  return data;
}

export async function fetchMyCustomerDeliveryPod(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/pod`, { headers: authHeaders(token) });
  if (response.status === 404) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load proof of delivery");
  return data;
}

export async function fetchPodSettings(token) {
  const response = await fetch(`${API_BASE_URL}/admin/pod-settings`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load POD settings");
  return data;
}

export async function updatePodSettings(token, settings) {
  const response = await fetch(`${API_BASE_URL}/admin/pod-settings`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(settings),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update POD settings");
  return data;
}

export async function exportPodReportCSV(token, dateFrom, dateTo) {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const response = await fetch(`${API_BASE_URL}/admin/pod-report?${params}`, { headers: authHeaders(token) });
  if (!response.ok) throw new Error("Failed to export POD report");
  return response.blob();
}

// ---------- SLA Management (Phase 2) ----------

export async function fetchSlaPolicies(token) {
  const response = await fetch(`${API_BASE_URL}/admin/sla/policies`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load SLA policies");
  return data;
}

export async function createSlaPolicy(token, policy) {
  const response = await fetch(`${API_BASE_URL}/admin/sla/policies`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(policy),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create SLA policy");
  return data;
}

export async function updateSlaPolicy(token, policyId, updates) {
  const response = await fetch(`${API_BASE_URL}/admin/sla/policies/${policyId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update SLA policy");
  return data;
}

export async function deleteSlaPolicy(token, policyId) {
  const response = await fetch(`${API_BASE_URL}/admin/sla/policies/${policyId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete SLA policy");
  return data;
}

export async function fetchSlaDashboard(token) {
  const response = await fetch(`${API_BASE_URL}/admin/sla/dashboard`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load SLA dashboard");
  return data;
}

export async function fetchSlaAnalytics(token) {
  const response = await fetch(`${API_BASE_URL}/admin/sla/analytics`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load SLA analytics");
  return data;
}

// ---------- Warehouse Management (Phase 3) ----------

export async function fetchWarehouses(token) {
  const response = await fetch(`${API_BASE_URL}/warehouses/`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load warehouses");
  return data;
}

export async function createWarehouse(token, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create warehouse");
  return data;
}

export async function updateWarehouse(token, warehouseId, updates) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update warehouse");
  return data;
}

export async function deleteWarehouse(token, warehouseId) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete warehouse");
  return data;
}

export async function fetchWarehouseInventory(token, warehouseId) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}/inventory`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load warehouse inventory");
  return data;
}

export async function fetchLowStock(token) {
  const response = await fetch(`${API_BASE_URL}/warehouses/low-stock`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load low-stock items");
  return data;
}

export async function stockIn(token, warehouseId, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}/stock-in`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to record stock-in");
  return data;
}

export async function stockOut(token, warehouseId, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}/stock-out`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to record stock-out");
  return data;
}

export async function adjustWarehouseStock(token, warehouseId, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}/adjust`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to adjust stock");
  return data;
}

export async function transferWarehouseStock(token, warehouseId, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}/transfer`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to transfer stock");
  return data;
}

export async function reportWarehouseDamage(token, warehouseId, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}/damage`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to report damage");
  return data;
}

export async function fetchStockMovements(token, warehouseId) {
  const response = await fetch(`${API_BASE_URL}/warehouses/${warehouseId}/movements`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load stock movements");
  return data;
}

export async function syncProductStockFromWarehouses(token, productId) {
  const response = await fetch(`${API_BASE_URL}/warehouses/products/${productId}/sync-stock`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to sync product stock");
  return data;
}

export async function fetchSuppliers(token) {
  const response = await fetch(`${API_BASE_URL}/warehouses/suppliers/`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load suppliers");
  return data;
}

export async function createSupplier(token, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/suppliers/`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create supplier");
  return data;
}

export async function fetchPurchaseOrders(token) {
  const response = await fetch(`${API_BASE_URL}/warehouses/purchase-orders/`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load purchase orders");
  return data;
}

export async function createPurchaseOrder(token, payload) {
  const response = await fetch(`${API_BASE_URL}/warehouses/purchase-orders/`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create purchase order");
  return data;
}

export async function receivePurchaseOrderItem(token, poId, itemId, receivedQuantity) {
  const response = await fetch(`${API_BASE_URL}/warehouses/purchase-orders/${poId}/items/${itemId}/receive`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ received_quantity: receivedQuantity }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to receive goods");
  return data;
}

// ---------- Granular RBAC (Phase 4) ----------

export async function fetchPermissionsCatalog(token) {
  const response = await fetch(`${API_BASE_URL}/admin/rbac/permissions-catalog`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load permissions catalog");
  return data.permissions;
}

export async function fetchMyPermissions(token) {
  const response = await fetch(`${API_BASE_URL}/admin/rbac/my-permissions`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load your permissions");
  return data.permissions;
}

export async function fetchCustomRoles(token) {
  const response = await fetch(`${API_BASE_URL}/admin/rbac/roles`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load custom roles");
  return data;
}

export async function createCustomRole(token, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/rbac/roles`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create custom role");
  return data;
}

export async function updateCustomRole(token, roleId, updates) {
  const response = await fetch(`${API_BASE_URL}/admin/rbac/roles/${roleId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(updates),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update custom role");
  return data;
}

export async function deleteCustomRole(token, roleId) {
  const response = await fetch(`${API_BASE_URL}/admin/rbac/roles/${roleId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete custom role");
  return data;
}

export async function assignCustomRole(token, userId, customRoleId) {
  const response = await fetch(`${API_BASE_URL}/admin/rbac/users/${userId}/role`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ custom_role_id: customRoleId }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update role assignment");
  return data;
}

// ---------- COD & Payment Reconciliation (Phase 5) ----------

export async function collectCod(token, deliveryId, collectedAmount, notes) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/cod/collect`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ collected_amount: collectedAmount, notes }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to record COD collection");
  return data;
}

export async function fetchCodCollection(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/cod`, { headers: authHeaders(token) });
  if (response.status === 404 || response.status === 400) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load COD collection");
  return data;
}

export async function fetchCodCollections(token, status, agentId) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (agentId) params.set("agent_id", agentId);
  const response = await fetch(`${API_BASE_URL}/admin/reconciliation/cod?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load COD collections");
  return data;
}

export async function createSettlement(token, agentId, notes) {
  const response = await fetch(`${API_BASE_URL}/admin/reconciliation/settlements`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ agent_id: agentId, notes }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create settlement");
  return data;
}

export async function fetchSettlements(token, agentId) {
  const params = new URLSearchParams();
  if (agentId) params.set("agent_id", agentId);
  const response = await fetch(`${API_BASE_URL}/admin/reconciliation/settlements?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load settlements");
  return data;
}

export async function settleSettlement(token, settlementId) {
  const response = await fetch(`${API_BASE_URL}/admin/reconciliation/settlements/${settlementId}/settle`, {
    method: "PATCH", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to settle");
  return data;
}

export async function fetchLedger(token, filters = {}) {
  const params = new URLSearchParams(filters);
  const response = await fetch(`${API_BASE_URL}/admin/reconciliation/ledger?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load ledger");
  return data;
}

export async function fetchFinancialDashboard(token) {
  const response = await fetch(`${API_BASE_URL}/admin/reconciliation/dashboard`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load financial dashboard");
  return data;
}

// ---------- Customer <-> Agent Communication (Phase 6) ----------

export async function fetchMessageTemplates(token) {
  const response = await fetch(`${API_BASE_URL}/message-templates`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load message templates");
  return data.templates;
}

export async function fetchDeliveryMessagesUnreadCount(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/messages/unread-count`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load unread count");
  return data.unread_count;
}

export async function fetchMyCustomerMessagesUnreadCount(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/messages/unread-count`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load unread count");
  return data.unread_count;
}

export async function sendCustomerMessage(token, deliveryId, message) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/messages`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ message }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to send message");
  return data;
}

export async function fetchCustomerMessages(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/customer/deliveries/${deliveryId}/messages`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load messages");
  return data;
}

// ---------- RTO Management (Phase 7) ----------

export async function fetchRtoRequests(token, status) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  const response = await fetch(`${API_BASE_URL}/admin/rto/requests?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load RTO requests");
  return data;
}

export async function approveRto(token, rtoId, note) {
  const response = await fetch(`${API_BASE_URL}/admin/rto/requests/${rtoId}/approve`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ note }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to approve RTO");
  return data;
}

export async function markRtoInTransit(token, rtoId) {
  const response = await fetch(`${API_BASE_URL}/admin/rto/requests/${rtoId}/in-transit`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update RTO");
  return data;
}

export async function markRtoReceived(token, rtoId) {
  const response = await fetch(`${API_BASE_URL}/admin/rto/requests/${rtoId}/received`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update RTO");
  return data;
}

export async function cancelRto(token, rtoId, note) {
  const response = await fetch(`${API_BASE_URL}/admin/rto/requests/${rtoId}/cancel`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ note }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to cancel RTO");
  return data;
}

export async function fetchRtoAnalytics(token) {
  const response = await fetch(`${API_BASE_URL}/admin/rto/analytics`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load RTO analytics");
  return data;
}

export async function fetchRtoSettings(token) {
  const response = await fetch(`${API_BASE_URL}/admin/rto/settings`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load RTO settings");
  return data;
}

export async function updateRtoSettings(token, rtoMaxAttempts) {
  const response = await fetch(`${API_BASE_URL}/admin/rto/settings`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify({ rto_max_attempts: rtoMaxAttempts }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update RTO settings");
  return data;
}

// ---------- Barcode/QR Package Scanning (Phase 8) ----------

export async function fetchPackageQrUrl(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/package-qr`, { headers: authHeaders(token) });
  if (!response.ok) throw new Error("Failed to load package QR code");
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

export async function resolveScannedCode(token, code) {
  const response = await fetch(`${API_BASE_URL}/scan/${encodeURIComponent(code)}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Invalid scan");
  return data;
}

export async function recordScan(token, deliveryId, payload) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/scan`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to record scan");
  return data;
}

export async function fetchScanHistory(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/scans`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load scan history");
  return data;
}

export async function fetchOrgScans(token, filters = {}) {
  const params = new URLSearchParams(filters);
  const response = await fetch(`${API_BASE_URL}/admin/scans?${params}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load scan log");
  return data;
}

// ---------- Advanced Routing (Phase 9) ----------

export async function fetchDynamicEta(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/eta`, { headers: authHeaders(token) });
  if (response.status === 404) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load ETA");
  return data;
}

export async function fetchRouteDeviation(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/route-deviation`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load route deviation");
  return data;
}

export async function fetchRouteReplay(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/route-replay`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load route replay");
  return data;
}

export async function fetchRouteEfficiency(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/deliveries/${deliveryId}/route-efficiency`, { headers: authHeaders(token) });
  if (response.status === 404) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load route efficiency");
  return data;
}

export async function fetchDeliveryHeatmap(token) {
  const response = await fetch(`${API_BASE_URL}/admin/routing/heatmap`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load heatmap");
  return data.points;
}

export async function optimizeMultiAgentRoutes(token, agentStarts) {
  const response = await fetch(`${API_BASE_URL}/admin/routing/optimize-multi-agent`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ agent_starts: agentStarts }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to optimize routes");
  return data.routes;
}

// ---------- Notification Templates (Phase 10) ----------

export async function fetchNotificationTemplates(token) {
  const response = await fetch(`${API_BASE_URL}/admin/notification-templates/`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load notification templates");
  return data;
}

export async function updateNotificationTemplate(token, eventType, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/notification-templates/${eventType}`, {
    method: "PUT", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update notification template");
  return data;
}

export async function resetNotificationTemplate(token, eventType) {
  const response = await fetch(`${API_BASE_URL}/admin/notification-templates/${eventType}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to reset notification template");
  return data;
}

// ---------- Fleet Management (Phase 11) ----------

export async function fetchVehicles(token, status) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles${qs}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load vehicles");
  return data;
}

export async function createVehicle(token, payload) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create vehicle");
  return data;
}

export async function updateVehicle(token, vehicleId, payload) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update vehicle");
  return data;
}

export async function deactivateVehicle(token, vehicleId) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to deactivate vehicle");
  return data;
}

export async function assignVehicle(token, vehicleId, agentId) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}/assign`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ agent_id: agentId }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to assign vehicle");
  return data;
}

export async function recordVehicleInspection(token, vehicleId, payload) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}/inspection`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to record inspection");
  return data;
}

export async function addVehicleMaintenance(token, vehicleId, payload) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}/maintenance`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to add maintenance record");
  return data;
}

export async function fetchVehicleMaintenance(token, vehicleId) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}/maintenance`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load maintenance records");
  return data;
}

export async function addVehicleFuelRecord(token, vehicleId, payload) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}/fuel`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to add fuel record");
  return data;
}

export async function fetchVehicleFuelRecords(token, vehicleId) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}/fuel`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load fuel records");
  return data;
}

export async function fetchVehicleUtilization(token, vehicleId, days = 30) {
  const response = await fetch(`${API_BASE_URL}/fleet/vehicles/${vehicleId}/utilization?days=${days}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load vehicle utilization");
  return data;
}

export async function fetchFleetUtilization(token, days = 30) {
  const response = await fetch(`${API_BASE_URL}/fleet/utilization?days=${days}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load fleet utilization");
  return data;
}

export async function fetchFleetReminders(token, withinDays = 14) {
  const response = await fetch(`${API_BASE_URL}/fleet/reminders?within_days=${withinDays}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load fleet reminders");
  return data;
}

// ---------- Customer Support (Phase 12) ----------

export async function createSupportTicket(token, payload) {
  const response = await fetch(`${API_BASE_URL}/customer/support/tickets`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create ticket");
  return data;
}

export async function fetchMySupportTickets(token) {
  const response = await fetch(`${API_BASE_URL}/customer/support/tickets`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load tickets");
  return data;
}

export async function fetchMySupportTicket(token, ticketId) {
  const response = await fetch(`${API_BASE_URL}/customer/support/tickets/${ticketId}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load ticket");
  return data;
}

export async function fetchMySupportTicketMessages(token, ticketId) {
  const response = await fetch(`${API_BASE_URL}/customer/support/tickets/${ticketId}/messages`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load messages");
  return data;
}

export async function replyToMySupportTicket(token, ticketId, message) {
  const response = await fetch(`${API_BASE_URL}/customer/support/tickets/${ticketId}/messages`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ message }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to send message");
  return data;
}

// ---------- Support (staff side, Phase 12) ----------

export async function fetchSupportTickets(token, filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== "") params.set(k, v); });
  const qs = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE_URL}/admin/support/tickets${qs}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load tickets");
  return data;
}

export async function fetchSupportTicketMessages(token, ticketId) {
  const response = await fetch(`${API_BASE_URL}/admin/support/tickets/${ticketId}/messages`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load messages");
  return data;
}

export async function replyToSupportTicket(token, ticketId, message, isInternalNote = false) {
  const response = await fetch(`${API_BASE_URL}/admin/support/tickets/${ticketId}/messages`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ message, is_internal_note: isInternalNote }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to send message");
  return data;
}

export async function updateSupportTicket(token, ticketId, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/support/tickets/${ticketId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update ticket");
  return data;
}

export async function resolveSupportTicket(token, ticketId, resolutionNotes) {
  const response = await fetch(`${API_BASE_URL}/admin/support/tickets/${ticketId}/resolve`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ resolution_notes: resolutionNotes }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to resolve ticket");
  return data;
}

export async function fetchSupportAnalytics(token) {
  const response = await fetch(`${API_BASE_URL}/admin/support/analytics`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load support analytics");
  return data;
}

// ---------- Finance & Invoicing (Phase 13) ----------

export async function fetchMyFinancialDocuments(token) {
  const response = await fetch(`${API_BASE_URL}/customer/finance/documents`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load documents");
  return data;
}

export function myFinancialDocumentPdfUrl(documentId) {
  return `${API_BASE_URL}/customer/finance/documents/${documentId}/pdf`;
}

export async function fetchFinancialDocuments(token, filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== "") params.set(k, v); });
  const qs = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE_URL}/admin/finance/documents${qs}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load documents");
  return data;
}

export function financialDocumentPdfUrl(documentId) {
  return `${API_BASE_URL}/admin/finance/documents/${documentId}/pdf`;
}

export async function createCreditNote(token, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/finance/credit-notes`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create credit note");
  return data;
}

export async function createDebitNote(token, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/finance/debit-notes`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create debit note");
  return data;
}

export async function fetchFinancialReport(token) {
  const response = await fetch(`${API_BASE_URL}/admin/finance/reports`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load financial report");
  return data;
}

async function _authedPdfFetch(url, token) {
  const response = await fetch(url, { headers: authHeaders(token) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to download PDF");
  }
  return response.blob();
}

export async function downloadFinancialDocumentPdf(token, documentId, isCustomer = false) {
  const url = isCustomer ? myFinancialDocumentPdfUrl(documentId) : financialDocumentPdfUrl(documentId);
  const blob = await _authedPdfFetch(url, token);
  const objectUrl = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = `${documentId}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(objectUrl);
}

// ---------- Public API & Webhooks (Phase 14) ----------

export async function fetchApiKeys(token) {
  const response = await fetch(`${API_BASE_URL}/admin/api-keys`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load API keys");
  return data;
}

export async function createApiKey(token, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/api-keys`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create API key");
  return data;
}

export async function rotateApiKey(token, keyId) {
  const response = await fetch(`${API_BASE_URL}/admin/api-keys/${keyId}/rotate`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to rotate API key");
  return data;
}

export async function revokeApiKey(token, keyId) {
  const response = await fetch(`${API_BASE_URL}/admin/api-keys/${keyId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to revoke API key");
  return data;
}

export async function fetchWebhooks(token) {
  const response = await fetch(`${API_BASE_URL}/admin/webhooks`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load webhooks");
  return data;
}

export async function createWebhook(token, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/webhooks`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create webhook");
  return data;
}

export async function updateWebhook(token, webhookId, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/webhooks/${webhookId}`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update webhook");
  return data;
}

export async function deleteWebhook(token, webhookId) {
  const response = await fetch(`${API_BASE_URL}/admin/webhooks/${webhookId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to delete webhook");
  return data;
}

export async function fetchWebhookDeliveries(token, webhookId, status) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const response = await fetch(`${API_BASE_URL}/admin/webhooks/${webhookId}/deliveries${qs}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load webhook deliveries");
  return data;
}

export async function replayWebhookDelivery(token, deliveryId) {
  const response = await fetch(`${API_BASE_URL}/admin/webhooks/deliveries/${deliveryId}/replay`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to replay delivery");
  return data;
}

// ---------- Advanced Analytics (Phase 15) ----------

export async function fetchAdvancedAnalytics(token, days = 30) {
  const response = await fetch(`${API_BASE_URL}/admin/analytics/advanced/?days=${days}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load advanced analytics");
  return data;
}

// ---------- Enterprise Organization Management (Phase 16) ----------

export async function updateOrgBranding(token, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/organization/branding`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update branding");
  return data;
}

export async function updateOrgLocale(token, payload) {
  const response = await fetch(`${API_BASE_URL}/admin/organization/locale`, {
    method: "PATCH", headers: authHeaders(token), body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to update locale");
  return data;
}

export async function fetchOrgUsage(token) {
  const response = await fetch(`${API_BASE_URL}/admin/organization/usage`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load usage metrics");
  return data;
}

export async function suspendOrg(token, reason) {
  const response = await fetch(`${API_BASE_URL}/admin/organization/suspend`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ reason }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to suspend organization");
  return data;
}

export async function reactivateOrg(token) {
  const response = await fetch(`${API_BASE_URL}/admin/organization/reactivate`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to reactivate organization");
  return data;
}

export async function exportOrgData(token) {
  const response = await fetch(`${API_BASE_URL}/admin/organization/export`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to export organization data");
  return data;
}

// ---------- Security & Session Management (Phase 17) ----------

export async function fetchMySessions(token, currentRefreshToken) {
  const qs = currentRefreshToken ? `?current_refresh_token=${encodeURIComponent(currentRefreshToken)}` : "";
  const response = await fetch(`${API_BASE_URL}/auth/sessions${qs}`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load sessions");
  return data;
}

export async function revokeMySession(token, sessionId) {
  const response = await fetch(`${API_BASE_URL}/auth/sessions/${sessionId}`, {
    method: "DELETE", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to revoke session");
  return data;
}

export async function logoutAllSessions(token) {
  const response = await fetch(`${API_BASE_URL}/auth/sessions/logout-all`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to log out all sessions");
  return data;
}

export async function fetchMyLoginHistory(token) {
  const response = await fetch(`${API_BASE_URL}/auth/login-history`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load login history");
  return data;
}

export async function fetchMySecurityEvents(token) {
  const response = await fetch(`${API_BASE_URL}/auth/security-events`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load security events");
  return data;
}

export async function regenerateRecoveryCodes(token, password) {
  const response = await fetch(`${API_BASE_URL}/auth/2fa/recovery-codes/generate`, {
    method: "POST", headers: authHeaders(token), body: JSON.stringify({ password }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to generate recovery codes");
  return data;
}

// ---------- Monitoring & Reliability (Phase 18) ----------

export async function fetchMonitoringStatus(token) {
  const response = await fetch(`${API_BASE_URL}/admin/monitoring/status`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load monitoring status");
  return data;
}

export async function fetchApiMetrics(token) {
  const response = await fetch(`${API_BASE_URL}/admin/monitoring/api-metrics`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load API metrics");
  return data;
}

export async function fetchNotificationMetrics(token) {
  const response = await fetch(`${API_BASE_URL}/admin/monitoring/notification-metrics`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load notification metrics");
  return data;
}

export async function fetchErrorLogs(token) {
  const response = await fetch(`${API_BASE_URL}/admin/monitoring/errors`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load error logs");
  return data;
}

export async function fetchBackups(token) {
  const response = await fetch(`${API_BASE_URL}/admin/monitoring/backups`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to load backups");
  return data;
}

export async function triggerBackup(token) {
  const response = await fetch(`${API_BASE_URL}/admin/monitoring/backups`, {
    method: "POST", headers: authHeaders(token),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to create backup");
  return data;
}

export async function verifyBackup(token, filename) {
  const response = await fetch(`${API_BASE_URL}/admin/monitoring/backups/${encodeURIComponent(filename)}/verify`, { headers: authHeaders(token) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Failed to verify backup");
  return data;
}
