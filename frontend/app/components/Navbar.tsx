"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { authStorage } from "@/lib/api";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [isAuth, setIsAuth] = useState(false);

  useEffect(() => {
    setIsAuth(authStorage.isLoggedIn());
  }, [pathname]);

  const handleLogout = () => {
    authStorage.clearToken();
    setIsAuth(false);
    router.push("/login");
  };

  if (pathname === "/login") {
    return (
      <header className="navbar">
        <div className="app-container navbar-inner">
          <Link href="/" className="brand-logo">
            <div className="brand-icon">M</div>
            <span>Meeting Assistant</span>
          </Link>
        </div>
      </header>
    );
  }

  return (
    <header className="navbar">
      <div className="app-container navbar-inner">
        <Link href="/" className="brand-logo">
          <div className="brand-icon">M</div>
          <span>Meeting Assistant</span>
        </Link>

        <nav className="nav-links">
          {isAuth ? (
            <>
              <Link
                href="/dashboard"
                className={`nav-link ${pathname === "/dashboard" ? "active" : ""}`}
              >
                Dashboard
              </Link>
              <Link
                href="/meetings"
                className={`nav-link ${pathname.startsWith("/meetings") ? "active" : ""}`}
              >
                Meetings
              </Link>
              <button
                onClick={handleLogout}
                className="btn btn-secondary btn-sm"
                style={{ marginLeft: 8 }}
              >
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="btn btn-primary btn-sm">
                Sign In
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
