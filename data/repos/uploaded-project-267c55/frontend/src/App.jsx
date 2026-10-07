import React, { useState, useEffect, useRef, Suspense, lazy } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { CustomerAuthProvider, useCustomerAuth } from "./context/CustomerAuthContext";
import { ToastProvider, useToast } from "./context/ToastContext";
import { ThemeProvider } from "./context/ThemeContext";
import { resendVerificationRequest, customerResendVerificationRequest } from "./services/authApi";
import ConnectivityBanner from "./components/ConnectivityBanner";
import VerificationBanner from "./components/VerificationBanner";
import Sidebar from "./components/Sidebar";
import AgentDeliveryList from "./components/AgentDeliveryList";
import DispatcherTable from "./components/DispatcherTable";
import LoginPage from "./components/LoginPage";
import SignupPage from "./components/SignupPage";
import ForgotPasswordPage from "./components/ForgotPasswordPage";
import ResetPasswordPage from "./components/ResetPasswordPage";
import VerifyEmailPage from "./components/VerifyEmailPage";
import TrackingPage from "./components/TrackingPage";
import CustomerDashboard from "./components/CustomerDashboard";

// Everything below this line is a role-gated admin/dispatcher "settings
// & reports" page reached only via a specific Sidebar nav click — never
// needed for the very first paint (login, the agent/dispatcher landing
// view, or the customer dashboard). Loading these lazily means the
// initial JS bundle a brand-new visitor downloads doesn't include, say,
// the finance/webhooks/monitoring admin panels they may never open in
// a session — each becomes its own chunk, fetched on first navigation
// to it (with a short "Loading..." fallback from the Suspense boundary
// below) instead of up front.
const AgentPerformance = lazy(() => import("./components/AgentPerformance"));
const ProductManager = lazy(() => import("./components/ProductManager"));
const AnalyticsDashboard = lazy(() => import("./components/AnalyticsDashboard"));
const AdvancedAnalyticsPanel = lazy(() => import("./components/AdvancedAnalyticsPanel"));
const AdminPanel = lazy(() => import("./components/AdminPanel"));
const AuditLogViewer = lazy(() => import("./components/AuditLogViewer"));
const ZoneManager = lazy(() => import("./components/ZoneManager"));
const FailedDeliveryReasonManager = lazy(() => import("./components/FailedDeliveryReasonManager"));
const MyWorkforce = lazy(() => import("./components/MyWorkforce"));
const WorkforceManager = lazy(() => import("./components/WorkforceManager"));
const ReturnRequestsPanel = lazy(() => import("./components/ReturnRequestsPanel"));
const TwoFactorSettings = lazy(() => import("./components/TwoFactorSettings"));
const SecurityDashboard = lazy(() => import("./components/SecurityDashboard"));
const AccountSettings = lazy(() => import("./components/AccountSettings"));
const SlaManager = lazy(() => import("./components/SlaManager"));
const PodSettingsPanel = lazy(() => import("./components/PodSettingsPanel"));
const WarehouseManager = lazy(() => import("./components/WarehouseManager"));
const FleetManager = lazy(() => import("./components/FleetManager"));
const SupportManager = lazy(() => import("./components/SupportManager"));
const FinanceManager = lazy(() => import("./components/FinanceManager"));
const ApiWebhooksManager = lazy(() => import("./components/ApiWebhooksManager"));
const OrganizationSettings = lazy(() => import("./components/OrganizationSettings"));
const MonitoringDashboard = lazy(() => import("./components/MonitoringDashboard"));
const RbacManager = lazy(() => import("./components/RbacManager"));
const ReconciliationDashboard = lazy(() => import("./components/ReconciliationDashboard"));
const RtoManager = lazy(() => import("./components/RtoManager"));
const RoutingInsights = lazy(() => import("./components/RoutingInsights"));
const NotificationTemplateManager = lazy(() => import("./components/NotificationTemplateManager"));

function LazyPageFallback() {
  return (
    <div style={{ padding: "40px", textAlign: "center", color: "var(--text-muted)", fontSize: "13px" }}>
      Loading…
    </div>
  );
}

function StaffDashboard({ user }) {
  const { token } = useAuth();
  const [activeView, setActiveView] = useState(null);
  const currentView = activeView || (user.role === "agent" ? "deliveries" : "dashboard");

  return (
    <div className="app-shell">
      <Sidebar activeView={currentView} onNavigate={setActiveView} />
      <div className="main-content">
        <ConnectivityBanner />
        <div style={{ marginTop: "20px" }}>
          {!user.email_verified && (
            <VerificationBanner onResend={() => resendVerificationRequest(token)} />
          )}
          {user.role === "agent" && currentView === "deliveries" && <AgentDeliveryList />}
          {(user.role === "dispatcher" || user.role === "admin") && currentView === "dashboard" && (
            <DispatcherTable />
          )}
          <Suspense fallback={<LazyPageFallback />}>
            {user.role === "agent" && currentView === "performance" && <AgentPerformance />}
            {user.role === "admin" && currentView === "admin" && <AdminPanel />}
            {user.role === "admin" && currentView === "zones" && <ZoneManager />}
            {user.role === "admin" && currentView === "reason-codes" && <FailedDeliveryReasonManager />}
            {user.role === "agent" && currentView === "workforce" && <MyWorkforce />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "workforce" && <WorkforceManager />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "returns" && (
              <ReturnRequestsPanel />
            )}
            {user.role === "admin" && currentView === "audit-log" && <AuditLogViewer />}
            {user.role === "admin" && currentView === "analytics" && <AnalyticsDashboard />}
            {user.role === "admin" && currentView === "advanced-analytics" && <AdvancedAnalyticsPanel />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "products" && (
              <ProductManager />
            )}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "sla" && <SlaManager />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "warehouses" && <WarehouseManager />}
            {currentView === "fleet" && (user.role === "dispatcher" || user.role === "admin" || user.role === "agent") && <FleetManager />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "support" && <SupportManager />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "invoicing" && <FinanceManager />}
            {user.role === "admin" && currentView === "api-webhooks" && <ApiWebhooksManager />}
            {user.role === "admin" && currentView === "organization" && <OrganizationSettings />}
            {user.role === "admin" && currentView === "monitoring" && <MonitoringDashboard />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "reconciliation" && <ReconciliationDashboard />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "rto" && <RtoManager />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "routing" && <RoutingInsights />}
            {(user.role === "dispatcher" || user.role === "admin") && currentView === "notification-templates" && <NotificationTemplateManager />}
            {user.role === "admin" && currentView === "pod-settings" && <PodSettingsPanel />}
            {user.role === "admin" && currentView === "rbac" && <RbacManager />}
            {currentView === "account" && <AccountSettings />}
            {currentView === "security" && (
              <div>
                <TwoFactorSettings />
                <SecurityDashboard />
              </div>
            )}
          </Suspense>
        </div>
      </div>
    </div>
  );
}

function AuthFlow() {
  const [view, setView] = useState("login");
  const [signupAccountType, setSignupAccountType] = useState("staff");
  const [forgotPasswordAccountType, setForgotPasswordAccountType] = useState("staff");

  if (view === "login") {
    return (
      <LoginPage
        onSwitchToSignup={(accountType) => {
          setSignupAccountType(accountType);
          setView("signup");
        }}
        onForgotPassword={(accountType) => {
          setForgotPasswordAccountType(accountType);
          setView("forgot-password");
        }}
      />
    );
  }
  if (view === "forgot-password") {
    return <ForgotPasswordPage onBackToLogin={() => setView("login")} accountType={forgotPasswordAccountType} />;
  }
  return (
    <SignupPage
      onSwitchToLogin={() => setView("login")}
      initialAccountType={signupAccountType}
    />
  );
}

function RootRouter() {
  const { user, isLoading: staffLoading, completeOAuthLogin } = useAuth();
  const { customer, isLoading: customerLoading, completeOAuthLogin: completeCustomerOAuthLogin } = useCustomerAuth();
  const { showToast } = useToast();
  const [isOAuthProcessing, setIsOAuthProcessing] = useState(false);
  const oauthHandledRef = useRef(false);

  useEffect(() => {
    // Surfaces a real Background Sync completion (see public/sw.js) —
    // including one that happened while every tab was closed, the
    // moment this tab is next open to show it.
    function handleBackgroundSync(event) {
      showToast(`Synced ${event.detail.syncedCount} item(s) that were queued while offline.`, "info");
    }
    window.addEventListener("background-sync-complete", handleBackgroundSync);
    return () => window.removeEventListener("background-sync-complete", handleBackgroundSync);
  }, [showToast]);

  const urlParams = new URLSearchParams(window.location.search);
  const resetToken = urlParams.get("reset_token");
  const customerResetToken = urlParams.get("customer_reset_token");
  const verifyEmailToken = urlParams.get("verify_email_token");
  const verifyCustomerEmailToken = urlParams.get("verify_customer_email_token");
  const trackId = urlParams.get("track");
  const oauthCode = urlParams.get("oauth_code");
  const oauthError = urlParams.get("oauth_error");
  const customerOauthCode = urlParams.get("customer_oauth_code");
  const customerOauthError = urlParams.get("customer_oauth_error");

  // Landing back here from the Google OAuth redirect (see
  // routes/auth.py's staff /oauth/google/callback and
  // routes/customer_auth.py's customer equivalent, plus
  // LoginPage/SignupPage's "Sign in with Google" buttons): either a
  // one-time oauth_code to exchange for a real session (see
  // AuthContext/CustomerAuthContext's completeOAuthLogin), or an
  // oauth_error to surface as a toast. Runs once per page load (the
  // ref guard) since the URL param itself is cleared right after, via
  // replaceState — same "strip the token from the URL once used"
  // pattern as ResetPasswordPage/VerifyEmailPage elsewhere in this
  // file. Staff and customer params are distinct (oauth_* vs
  // customer_oauth_*) since only one of the two login flows can be
  // relevant to any single redirect, but both land on this same root
  // route.
  useEffect(() => {
    if (oauthHandledRef.current) return;
    if (oauthError || customerOauthError) {
      oauthHandledRef.current = true;
      showToast(oauthError || customerOauthError, "error");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (oauthCode || customerOauthCode) {
      oauthHandledRef.current = true;
      setIsOAuthProcessing(true);
      const exchange = oauthCode ? completeOAuthLogin(oauthCode) : completeCustomerOAuthLogin(customerOauthCode);
      exchange
        .catch((err) => showToast(err.message, "error"))
        .finally(() => {
          window.history.replaceState({}, "", window.location.pathname);
          setIsOAuthProcessing(false);
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (trackId) return <TrackingPage deliveryId={trackId} />;

  if (resetToken || customerResetToken) {
    return (
      <ResetPasswordPage
        token={resetToken || customerResetToken}
        accountType={customerResetToken ? "customer" : "staff"}
        onDone={() => {
          window.history.replaceState({}, "", window.location.pathname);
          window.location.reload();
        }}
      />
    );
  }

  if (verifyEmailToken || verifyCustomerEmailToken) {
    return (
      <VerifyEmailPage
        token={verifyEmailToken || verifyCustomerEmailToken}
        accountType={verifyCustomerEmailToken ? "customer" : "staff"}
        onDone={() => {
          window.history.replaceState({}, "", window.location.pathname);
          window.location.reload();
        }}
      />
    );
  }

  if (staffLoading || customerLoading) return null;

  if (isOAuthProcessing) {
    return (
      <div style={{ padding: "60px", textAlign: "center", color: "var(--text-muted)", fontSize: "14px" }}>
        Signing you in…
      </div>
    );
  }

  if (user) return <StaffDashboard user={user} />;
  if (customer) return <CustomerDashboard />;

  return <AuthFlow />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <CustomerAuthProvider>
          <ToastProvider>
            <RootRouter />
          </ToastProvider>
        </CustomerAuthProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
