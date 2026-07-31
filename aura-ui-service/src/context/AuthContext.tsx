"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { AuthResponse } from "@/lib/api";

interface AuthContextType {
  user: AuthResponse | null;
  login: (data: AuthResponse) => void;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const initializeAuth = () => {
      try {
        const storedUser = localStorage.getItem("aura_user");
        if (storedUser) {
          setUser(JSON.parse(storedUser));
        }
      } catch (error) {
        console.error("Failed to parse stored user data:", error);
        localStorage.removeItem("aura_user");
        localStorage.removeItem("aura_token");
      } finally {
        setIsLoading(false);
      }
    };

    initializeAuth();

    // Listen for storage events (syncs login/logout state across browser tabs)
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === "aura_user") {
        if (event.newValue) {
          setUser(JSON.parse(event.newValue));
        } else {
          setUser(null);
          router.push("/login");
        }
      }
    };

    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, [router]);

  const login = useCallback(
    (data: AuthResponse) => {
      setUser(data);
      localStorage.setItem("aura_user", JSON.stringify(data));
      if (data.access_token) {
        localStorage.setItem("aura_token", data.access_token);
      }
      router.push("/");
    },
    [router]
  );

  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem("aura_user");
    localStorage.removeItem("aura_token");
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}