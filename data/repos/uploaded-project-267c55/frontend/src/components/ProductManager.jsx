import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import {
  fetchMyProducts,
  createProduct,
  updateProduct,
  deleteProduct,
  setStoreVisibility,
  setStorePricing,
  setStoreSlotSettings,
  setStoreProfile,
  fetchMyOrganization,
  uploadProductImage,
  fetchMyCoupons,
  createCoupon,
  updateCoupon,
  deleteCoupon,
  API_BASE_URL,
} from "../services/api";
import {
  setActiveDispatcher,
  queueDispatcherAction,
  getQueuedDispatcherActions,
} from "../services/dispatcherCache";
import { startDispatcherActionAutoSync } from "../services/dispatcherSyncEngine";
import { writeSyncContext } from "../services/backgroundSyncContext";
import "../styles/auth.css";

// image_url from the backend is a relative path like "/uploads/products/xyz.jpg" —
// resolve it against the API host so <img> tags actually load it. Leaves
// absolute URLs (http://..., https://...) alone.
function resolveImageUrl(imageUrl) {
  if (!imageUrl) return null;
  if (/^https?:\/\//i.test(imageUrl)) return imageUrl;
  return `${API_BASE_URL}${imageUrl}`;
}

export default function ProductManager() {
  const { token, user } = useAuth();
  const [products, setProducts] = useState([]);
  const [isPublic, setIsPublic] = useState(false);
  const [deliveryFee, setDeliveryFee] = useState("0");
  const [taxRatePercent, setTaxRatePercent] = useState("0");
  const [isPricingSaving, setIsPricingSaving] = useState(false);
  const [pricingError, setPricingError] = useState(null);
  const [pricingSaved, setPricingSaved] = useState(false);
  const [slotDurationMinutes, setSlotDurationMinutes] = useState("120");
  const [slotWindowStartHour, setSlotWindowStartHour] = useState("9");
  const [slotWindowEndHour, setSlotWindowEndHour] = useState("21");
  const [maxOrdersPerSlot, setMaxOrdersPerSlot] = useState("10");
  const [isSlotSettingsSaving, setIsSlotSettingsSaving] = useState(false);
  const [slotSettingsError, setSlotSettingsError] = useState(null);
  const [slotSettingsSaved, setSlotSettingsSaved] = useState(false);
  const [storeCategory, setStoreCategory] = useState("");
  const [storeDescription, setStoreDescription] = useState("");
  const [isProfileSaving, setIsProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState(null);
  const [profileSaved, setProfileSaved] = useState(false);
  const [coupons, setCoupons] = useState([]);
  const [isAddingCoupon, setIsAddingCoupon] = useState(false);
  const [couponCode, setCouponCode] = useState("");
  const [couponType, setCouponType] = useState("percent");
  const [couponValue, setCouponValue] = useState("");
  const [couponMinOrder, setCouponMinOrder] = useState("");
  const [couponMaxUses, setCouponMaxUses] = useState("");
  const [couponError, setCouponError] = useState(null);
  const [isAdding, setIsAdding] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");
  const [category, setCategory] = useState("");
  const [stockQuantity, setStockQuantity] = useState("");
  const [imageUrl, setImageUrl] = useState(null);
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const [imageUploadError, setImageUploadError] = useState(null);
  const [error, setError] = useState(null);
  const [pendingActionCount, setPendingActionCount] = useState(0);
  const [pendingActionMsg, setPendingActionMsg] = useState(null);

  useEffect(() => {
    setActiveDispatcher(user.id);
    writeSyncContext({ userId: user.id, token, role: user.role, apiBaseUrl: API_BASE_URL });

    load();
    if (user.role === "admin") loadOrgVisibility();
    loadCoupons();
    refreshPendingActionCount();

    const stopSync = startDispatcherActionAutoSync(token, (result) => {
      refreshPendingActionCount();
      if (result.syncedCount > 0) {
        setPendingActionMsg(`Synced ${result.syncedCount} queued product change(s) from earlier.`);
        load();
      }
      if (result.failed.length > 0) {
        setPendingActionMsg(`${result.failed.length} queued change(s) couldn't be applied: ${result.failed[0].message}`);
      }
    });

    return () => stopSync();
  }, []);

  async function refreshPendingActionCount() {
    const queued = await getQueuedDispatcherActions();
    setPendingActionCount(queued.filter((a) => a.type.includes("product")).length);
  }

  async function loadOrgVisibility() {
    try {
      const org = await fetchMyOrganization(token);
      setIsPublic(!!org.is_public_store);
      setDeliveryFee(String(org.delivery_fee ?? 0));
      setTaxRatePercent(String(org.tax_rate_percent ?? 0));
      setSlotDurationMinutes(String(org.slot_duration_minutes ?? 120));
      setSlotWindowStartHour(String(org.slot_window_start_hour ?? 9));
      setSlotWindowEndHour(String(org.slot_window_end_hour ?? 21));
      setMaxOrdersPerSlot(String(org.max_orders_per_slot ?? 10));
      setStoreCategory(org.category || "");
      setStoreDescription(org.description || "");
    } catch (err) {
      console.warn("Could not load store visibility:", err.message);
    }
  }

  async function loadCoupons() {
    try {
      setCoupons(await fetchMyCoupons(token));
    } catch (err) {
      console.warn("Could not load coupons:", err.message);
    }
  }

  async function handleSavePricing(e) {
    e.preventDefault();
    setPricingError(null);
    setPricingSaved(false);
    setIsPricingSaving(true);
    try {
      await setStorePricing(token, parseFloat(deliveryFee) || 0, parseFloat(taxRatePercent) || 0);
      setPricingSaved(true);
    } catch (err) {
      setPricingError(err instanceof TypeError ? "You're offline — try again once you're back online." : err.message);
    } finally {
      setIsPricingSaving(false);
    }
  }

  async function handleSaveSlotSettings(e) {
    e.preventDefault();
    setSlotSettingsError(null);
    setSlotSettingsSaved(false);
    setIsSlotSettingsSaving(true);
    try {
      await setStoreSlotSettings(token, {
        slot_duration_minutes: parseInt(slotDurationMinutes, 10) || 120,
        slot_window_start_hour: parseInt(slotWindowStartHour, 10) || 0,
        slot_window_end_hour: parseInt(slotWindowEndHour, 10) || 0,
        max_orders_per_slot: parseInt(maxOrdersPerSlot, 10) || 1,
      });
      setSlotSettingsSaved(true);
    } catch (err) {
      setSlotSettingsError(err instanceof TypeError ? "You're offline — try again once you're back online." : err.message);
    } finally {
      setIsSlotSettingsSaving(false);
    }
  }

  async function handleSaveProfile(e) {
    e.preventDefault();
    setProfileError(null);
    setProfileSaved(false);
    setIsProfileSaving(true);
    try {
      await setStoreProfile(token, storeCategory.trim(), storeDescription.trim());
      setProfileSaved(true);
    } catch (err) {
      setProfileError(err instanceof TypeError ? "You're offline — try again once you're back online." : err.message);
    } finally {
      setIsProfileSaving(false);
    }
  }

  async function handleAddCoupon(e) {
    e.preventDefault();
    setCouponError(null);
    try {
      await createCoupon(token, {
        code: couponCode.trim(),
        discount_type: couponType,
        discount_value: parseFloat(couponValue),
        min_order_value: couponMinOrder ? parseFloat(couponMinOrder) : null,
        max_uses: couponMaxUses ? parseInt(couponMaxUses, 10) : null,
      });
      setCouponCode("");
      setCouponType("percent");
      setCouponValue("");
      setCouponMinOrder("");
      setCouponMaxUses("");
      setIsAddingCoupon(false);
      await loadCoupons();
    } catch (err) {
      setCouponError(err instanceof TypeError ? "You're offline — try again once you're back online." : err.message);
    }
  }

  async function handleToggleCouponActive(coupon) {
    try {
      await updateCoupon(token, coupon.id, { is_active: !coupon.is_active });
      await loadCoupons();
    } catch (err) {
      setCouponError(err.message);
    }
  }

  async function handleDeleteCoupon(coupon) {
    if (!window.confirm(`Delete coupon "${coupon.code}"? This can't be undone.`)) return;
    try {
      await deleteCoupon(token, coupon.id);
      await loadCoupons();
    } catch (err) {
      setCouponError(err.message);
    }
  }

  async function load() {
    try {
      const data = await fetchMyProducts(token);
      setProducts(data);
      setError(null);
    } catch (err) {
      if (!(err instanceof TypeError)) setError(err.message);
      // Offline: keep showing whatever's already in state (plus any
      // optimistic local changes below) rather than clearing the list.
    }
  }

  async function handleImageSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImageUploadError(null);
    setIsUploadingImage(true);
    try {
      const result = await uploadProductImage(token, file);
      setImageUrl(result.image_url);
    } catch (err) {
      setImageUploadError(err instanceof TypeError ? "You're offline — image upload needs a connection." : err.message);
    } finally {
      setIsUploadingImage(false);
      e.target.value = ""; // allow re-selecting the same file later
    }
  }

  async function handleAdd(e) {
    e.preventDefault();
    setError(null);
    const payload = {
      name: name.trim(),
      description: description.trim() || null,
      price: parseFloat(price),
      category: category.trim() || null,
      image_url: imageUrl || null,
      stock_quantity: stockQuantity.trim() === "" ? null : parseInt(stockQuantity, 10),
    };
    try {
      await createProduct(token, payload);
      setName("");
      setDescription("");
      setPrice("");
      setCategory("");
      setStockQuantity("");
      setImageUrl(null);
      setIsAdding(false);
      await load();
    } catch (err) {
      if (err instanceof TypeError) {
        // Offline — queue it and show it locally right away (tagged
        // pending) instead of losing what was typed in.
        await queueDispatcherAction("create_product", payload);
        await refreshPendingActionCount();
        setProducts((prev) => [
          ...prev,
          { id: `pending-${Date.now()}`, org_id: null, is_active: true, created_at: new Date().toISOString(), _pending: true, ...payload },
        ]);
        setName("");
        setDescription("");
        setPrice("");
        setCategory("");
        setStockQuantity("");
        setImageUrl(null);
        setIsAdding(false);
      } else {
        setError(err.message);
      }
    }
  }

  async function handleToggleActive(product) {
    if (product._pending) return; // can't toggle something that hasn't been created on the server yet
    const nextActive = !product.is_active;
    try {
      await updateProduct(token, product.id, { is_active: nextActive });
      await load();
    } catch (err) {
      if (err instanceof TypeError) {
        await queueDispatcherAction("update_product", { product_id: product.id, updates: { is_active: nextActive } });
        await refreshPendingActionCount();
        setProducts((prev) => prev.map((p) => (p.id === product.id ? { ...p, is_active: nextActive, _pendingSync: true } : p)));
      } else {
        setError(err.message);
      }
    }
  }

  async function handleDelete(product) {
    if (!window.confirm("Delete this product? This can't be undone.")) return;
    if (product._pending) {
      // Never left the device — just drop it locally, nothing to queue.
      setProducts((prev) => prev.filter((p) => p.id !== product.id));
      return;
    }
    try {
      await deleteProduct(token, product.id);
      await load();
    } catch (err) {
      if (err instanceof TypeError) {
        await queueDispatcherAction("delete_product", { product_id: product.id });
        await refreshPendingActionCount();
        setProducts((prev) => prev.filter((p) => p.id !== product.id));
      } else {
        setError(err.message);
      }
    }
  }

  async function handleUpdateStock(product, newStock) {
    if (product._pending) return;
    const value = newStock.trim() === "" ? null : parseInt(newStock, 10);
    if (newStock.trim() !== "" && (Number.isNaN(value) || value < 0)) return;
    try {
      await updateProduct(token, product.id, { stock_quantity: value });
      await load();
    } catch (err) {
      if (err instanceof TypeError) {
        await queueDispatcherAction("update_product", { product_id: product.id, updates: { stock_quantity: value } });
        await refreshPendingActionCount();
        setProducts((prev) => prev.map((p) => (p.id === product.id ? { ...p, stock_quantity: value, _pendingSync: true } : p)));
      } else {
        setError(err.message);
      }
    }
  }

  async function handleToggleStore() {
    const next = !isPublic;
    setIsPublic(next);
    try {
      await setStoreVisibility(token, next);
    } catch (err) {
      setIsPublic(!next); // revert on failure — store visibility isn't queued offline, it's a single toggle best applied live
      setError(err instanceof TypeError ? "You're offline — try again once you're back online." : err.message);
    }
  }

  return (
    <div>
      <h2 className="page-title">Products</h2>

      {pendingActionCount > 0 && (
        <div className="connectivity-banner offline" style={{ marginBottom: "16px" }}>
          {pendingActionCount} product change(s) queued while offline — will sync automatically once you're back online.
        </div>
      )}

      {pendingActionMsg && (
        <p style={{ fontSize: "12.5px", color: "var(--accent)", marginBottom: "12px" }}>
          {pendingActionMsg}
        </p>
      )}

      {user.role === "admin" && (
        <div className="card" style={{ marginBottom: "20px", maxWidth: "500px" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "13.5px", cursor: "pointer" }}>
            <input type="checkbox" checked={isPublic} onChange={handleToggleStore} />
            <div>
              <strong>Public Storefront</strong>
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", fontWeight: 400 }}>
                When on, customers can browse and buy from your active
                products at the public store list.
              </div>
            </div>
          </label>
        </div>
      )}

      {user.role === "admin" && (
        <div className="card" style={{ marginBottom: "20px", maxWidth: "500px" }}>
          <strong style={{ fontSize: "13.5px" }}>Marketplace Listing</strong>
          <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: "4px 0 10px" }}>
            Shown on the public store directory — helps customers find and filter your store.
          </p>
          <form onSubmit={handleSaveProfile} style={{ display: "grid", gap: "8px" }}>
            <div className="auth-field">
              <label>Category</label>
              <input
                className="input" type="text" placeholder="e.g. Grocery, Electronics, Pharmacy"
                value={storeCategory} onChange={(e) => setStoreCategory(e.target.value)}
              />
            </div>
            <div className="auth-field">
              <label>Description</label>
              <input
                className="input" type="text" placeholder="A short line shown on your store card"
                value={storeDescription} onChange={(e) => setStoreDescription(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-primary" style={{ fontSize: "12px" }} disabled={isProfileSaving}>
              {isProfileSaving ? "Saving..." : "Save"}
            </button>
            {profileSaved && <p style={{ fontSize: "12px", color: "var(--accent)", marginTop: "4px" }}>Saved.</p>}
            {profileError && <p style={{ fontSize: "12px", color: "var(--danger)", marginTop: "4px" }}>{profileError}</p>}
          </form>
        </div>
      )}

      {user.role === "admin" && (
        <div className="card" style={{ marginBottom: "20px", maxWidth: "500px" }}>
          <strong style={{ fontSize: "13.5px" }}>Delivery Fee &amp; Tax (GST)</strong>
          <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: "4px 0 10px" }}>
            Applied to every checkout at your store, on top of the product subtotal.
          </p>
          <form onSubmit={handleSavePricing} style={{ display: "flex", gap: "10px", alignItems: "flex-end", flexWrap: "wrap" }}>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label>Delivery fee (₹)</label>
              <input className="input" type="number" step="0.01" min="0" value={deliveryFee} onChange={(e) => setDeliveryFee(e.target.value)} style={{ width: "110px" }} />
            </div>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label>GST rate (%)</label>
              <input className="input" type="number" step="0.01" min="0" value={taxRatePercent} onChange={(e) => setTaxRatePercent(e.target.value)} style={{ width: "110px" }} />
            </div>
            <button type="submit" className="btn btn-primary" style={{ fontSize: "12px" }} disabled={isPricingSaving}>
              {isPricingSaving ? "Saving..." : "Save"}
            </button>
          </form>
          {pricingSaved && <p style={{ fontSize: "12px", color: "var(--accent)", marginTop: "6px" }}>Saved.</p>}
          {pricingError && <p style={{ fontSize: "12px", color: "var(--danger)", marginTop: "6px" }}>{pricingError}</p>}
        </div>
      )}

      {user.role === "admin" && (
        <div className="card" style={{ marginBottom: "20px", maxWidth: "500px" }}>
          <strong style={{ fontSize: "13.5px" }}>Delivery Time Slots</strong>
          <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: "4px 0 10px" }}>
            Lets customers pick a delivery window at checkout instead of ASAP-only delivery.
          </p>
          <form onSubmit={handleSaveSlotSettings} style={{ display: "flex", gap: "10px", alignItems: "flex-end", flexWrap: "wrap" }}>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label>Slot length (min)</label>
              <input className="input" type="number" step="15" min="15" value={slotDurationMinutes} onChange={(e) => setSlotDurationMinutes(e.target.value)} style={{ width: "100px" }} />
            </div>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label>Opens (24h)</label>
              <input className="input" type="number" min="0" max="23" value={slotWindowStartHour} onChange={(e) => setSlotWindowStartHour(e.target.value)} style={{ width: "80px" }} />
            </div>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label>Closes (24h)</label>
              <input className="input" type="number" min="0" max="23" value={slotWindowEndHour} onChange={(e) => setSlotWindowEndHour(e.target.value)} style={{ width: "80px" }} />
            </div>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label>Max orders/slot</label>
              <input className="input" type="number" min="1" value={maxOrdersPerSlot} onChange={(e) => setMaxOrdersPerSlot(e.target.value)} style={{ width: "100px" }} />
            </div>
            <button type="submit" className="btn btn-primary" style={{ fontSize: "12px" }} disabled={isSlotSettingsSaving}>
              {isSlotSettingsSaving ? "Saving..." : "Save"}
            </button>
          </form>
          {slotSettingsSaved && <p style={{ fontSize: "12px", color: "var(--accent)", marginTop: "6px" }}>Saved.</p>}
          {slotSettingsError && <p style={{ fontSize: "12px", color: "var(--danger)", marginTop: "6px" }}>{slotSettingsError}</p>}
        </div>
      )}

      <div className="card" style={{ marginBottom: "20px", maxWidth: "500px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <strong style={{ fontSize: "13.5px" }}>Coupons</strong>
          <button className="btn" style={{ fontSize: "12px" }} onClick={() => setIsAddingCoupon(!isAddingCoupon)}>
            {isAddingCoupon ? "Cancel" : "+ New Coupon"}
          </button>
        </div>

        {isAddingCoupon && (
          <form onSubmit={handleAddCoupon} style={{ marginTop: "12px" }}>
            <div className="auth-field">
              <label>Code</label>
              <input className="input" type="text" value={couponCode} onChange={(e) => setCouponCode(e.target.value)} required placeholder="SAVE10" />
            </div>
            <div style={{ display: "flex", gap: "10px" }}>
              <div className="auth-field" style={{ flex: 1 }}>
                <label>Type</label>
                <select className="input" value={couponType} onChange={(e) => setCouponType(e.target.value)}>
                  <option value="percent">Percent off</option>
                  <option value="flat">Flat amount off</option>
                </select>
              </div>
              <div className="auth-field" style={{ flex: 1 }}>
                <label>{couponType === "percent" ? "Percent (%)" : "Amount (₹)"}</label>
                <input className="input" type="number" step="0.01" min="0" value={couponValue} onChange={(e) => setCouponValue(e.target.value)} required />
              </div>
            </div>
            <div style={{ display: "flex", gap: "10px" }}>
              <div className="auth-field" style={{ flex: 1 }}>
                <label>Min order (₹, optional)</label>
                <input className="input" type="number" step="0.01" min="0" value={couponMinOrder} onChange={(e) => setCouponMinOrder(e.target.value)} />
              </div>
              <div className="auth-field" style={{ flex: 1 }}>
                <label>Max uses (optional)</label>
                <input className="input" type="number" step="1" min="1" value={couponMaxUses} onChange={(e) => setCouponMaxUses(e.target.value)} />
              </div>
            </div>
            {couponError && <p style={{ color: "var(--danger)", fontSize: "12px" }}>{couponError}</p>}
            <button type="submit" className="btn btn-primary" style={{ fontSize: "12px" }}>Create Coupon</button>
          </form>
        )}

        <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
          {coupons.map((c) => (
            <div key={c.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--border-color)", opacity: c.is_active ? 1 : 0.5 }}>
              <div>
                <strong style={{ fontSize: "13px" }}>{c.code}</strong>
                <div style={{ fontSize: "11.5px", color: "var(--text-secondary)" }}>
                  {c.discount_type === "percent" ? `${c.discount_value}% off` : `₹${c.discount_value} off`}
                  {c.min_order_value ? ` · min ₹${c.min_order_value}` : ""}
                  {c.max_uses ? ` · ${c.used_count}/${c.max_uses} used` : ` · ${c.used_count} used`}
                </div>
              </div>
              <div style={{ display: "flex", gap: "6px" }}>
                <button className="btn" style={{ fontSize: "11px" }} onClick={() => handleToggleCouponActive(c)}>
                  {c.is_active ? "Deactivate" : "Activate"}
                </button>
                <button className="btn" style={{ fontSize: "11px", color: "var(--danger)" }} onClick={() => handleDeleteCoupon(c)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
          {coupons.length === 0 && !isAddingCoupon && (
            <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>No coupons yet.</p>
          )}
        </div>
      </div>

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      <button className="btn btn-primary" style={{ marginBottom: "16px" }} onClick={() => setIsAdding(!isAdding)}>
        {isAdding ? "Cancel" : "+ Add Product"}
      </button>

      {isAdding && (
        <form onSubmit={handleAdd} className="card" style={{ maxWidth: "420px", marginBottom: "20px" }}>
          <div className="auth-field">
            <label>Name</label>
            <input className="input" type="text" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>Description</label>
            <input className="input" type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="auth-field">
            <label>Price (₹)</label>
            <input className="input" type="number" step="0.01" min="0" value={price} onChange={(e) => setPrice(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>Category</label>
            <input className="input" type="text" value={category} onChange={(e) => setCategory(e.target.value)} />
          </div>
          <div className="auth-field">
            <label>Stock quantity (leave blank for unlimited)</label>
            <input className="input" type="number" step="1" min="0" placeholder="Unlimited" value={stockQuantity} onChange={(e) => setStockQuantity(e.target.value)} />
          </div>
          <div className="auth-field">
            <label>Photo</label>
            <input className="input" type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={handleImageSelect} />
            {isUploadingImage && <p style={{ fontSize: "12px", color: "var(--text-secondary)" }}>Uploading...</p>}
            {imageUploadError && <p style={{ fontSize: "12px", color: "var(--danger)" }}>{imageUploadError}</p>}
            {imageUrl && !isUploadingImage && (
              <img
                src={resolveImageUrl(imageUrl)}
                alt="Product preview"
                style={{ marginTop: "8px", width: "80px", height: "80px", objectFit: "cover", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-color)" }}
              />
            )}
          </div>
          <button type="submit" className="btn btn-primary" disabled={isUploadingImage}>Save Product</button>
        </form>
      )}

      <div style={{ display: "grid", gap: "10px" }}>
        {products.map((p) => (
          <div key={p.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", opacity: p.is_active ? 1 : 0.5 }}>
            <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
              {p.image_url ? (
                <img
                  src={resolveImageUrl(p.image_url)}
                  alt={p.name}
                  style={{ width: "56px", height: "56px", objectFit: "cover", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-color)", flexShrink: 0 }}
                />
              ) : (
                <div style={{ width: "56px", height: "56px", borderRadius: "var(--radius-sm)", border: "1px dashed var(--border-color)", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "10px", color: "var(--text-muted)", textAlign: "center" }}>
                  No photo
                </div>
              )}
              <div>
                <strong style={{ fontSize: "14px" }}>{p.name}</strong>
                {p.category && <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}> · {p.category}</span>}
                {(p._pending || p._pendingSync) && (
                  <span style={{ fontSize: "11px", color: "var(--accent)" }}> · queued offline</span>
                )}
                <div style={{ fontSize: "13px", color: "var(--accent)", fontWeight: 600 }}>₹{p.price.toFixed(2)}</div>
                {p.description && <div style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{p.description}</div>}
                {p.review_count > 0 && (
                  <div style={{ fontSize: "11.5px", color: "var(--text-secondary)" }}>
                    ★ {p.average_rating} ({p.review_count} review{p.review_count === 1 ? "" : "s"})
                  </div>
                )}
                <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                  <label style={{ fontSize: "11.5px", color: "var(--text-secondary)" }}>Stock:</label>
                  <input
                    type="number"
                    step="1"
                    min="0"
                    placeholder="Unlimited"
                    defaultValue={p.stock_quantity === null || p.stock_quantity === undefined ? "" : p.stock_quantity}
                    onBlur={(e) => handleUpdateStock(p, e.target.value)}
                    disabled={p._pending}
                    style={{ width: "72px", fontSize: "11.5px", padding: "2px 6px" }}
                    className="input"
                  />
                  {p.stock_quantity === 0 && (
                    <span style={{ fontSize: "11px", color: "var(--danger)", fontWeight: 600 }}>Out of stock</span>
                  )}
                </div>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button className="btn" style={{ fontSize: "12px" }} onClick={() => handleToggleActive(p)} disabled={p._pending}>
                {p.is_active ? "Deactivate" : "Activate"}
              </button>
              <button className="btn" style={{ fontSize: "12px", color: "var(--danger)" }} onClick={() => handleDelete(p)}>
                Delete
              </button>
            </div>
          </div>
        ))}
        {products.length === 0 && !isAdding && (
          <p style={{ color: "var(--text-secondary)" }}>No products yet — add your first one above.</p>
        )}
      </div>
    </div>
  );
}
