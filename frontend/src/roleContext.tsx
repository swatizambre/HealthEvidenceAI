import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearAuthToken,
  getAuthCapabilities,
  getAuthMe,
  setAuthOrgCode,
  setAuthPatientId,
  setAuthRoles,
  type AuthMe,
} from "./api";

/** Desk + patient identities across clinic to teaching-hospital settings. */
export type DeskRole =
  | "patient"
  | "staff"
  | "resident"
  | "senior_clinician"
  | "admin";

/** India rural→urban desk modes (maps to demo org tenants where seeded). */
export type FacilityType =
  | "phc"
  | "chc"
  | "taluk"
  | "district"
  | "clinic"
  | "multispecialty"
  | "superspecialty"
  | "government";

const FACILITY_ORG: Partial<Record<FacilityType, string>> = {
  phc: "ORG-000002",
  chc: "ORG-000003",
  district: "ORG-000004",
  multispecialty: "ORG-000001",
  superspecialty: "ORG-000001",
  government: "ORG-000001",
  clinic: "ORG-000002",
  taluk: "ORG-000003",
};

type RoleContextValue = {
  role: DeskRole;
  setRole: (role: DeskRole) => void;
  facility: FacilityType;
  setFacility: (facility: FacilityType) => void;
  myPatientId: string;
  setMyPatientId: (patientId: string) => void;
  isPatient: boolean;
  isSenior: boolean;
  isResident: boolean;
  isStaff: boolean;
  isAdmin: boolean;
  canPrepare: boolean;
  canDocument: boolean;
  canCheckEvidence: boolean;
  canAdjudicate: boolean;
  label: string;
  facilityLabel: string;
  /** True when local/pilot dig-jwt UAT minting is allowed. */
  demoSigninAllowed: boolean;
  authMode: string;
  signedInSubject: string;
  loadingAuth: boolean;
};

const ROLE_KEY = "he.ai.deskRole";
const FACILITY_KEY = "he.ai.facilityType";
const MY_PATIENT_KEY = "he.ai.myPatientId";

const RoleContext = createContext<RoleContextValue | null>(null);

const ROLE_LABELS: Record<DeskRole, string> = {
  patient: "Patient (my record)",
  staff: "Records / TPA desk clerk",
  resident: "Junior doctor / PG / MO (junior)",
  senior_clinician: "Consultant / senior MO",
  admin: "Facility / HIS admin",
};

const FACILITY_LABELS: Record<FacilityType, string> = {
  phc: "PHC / sub-centre OPD",
  chc: "CHC / block hospital",
  taluk: "Taluk / tehsil hospital",
  district: "District hospital",
  clinic: "Clinic / nursing home",
  multispecialty: "Urban multispecialty hospital",
  superspecialty: "Super-specialty / corporate centre",
  government: "Medical college / teaching hospital",
};

const ALL_FACILITIES: FacilityType[] = [
  "phc",
  "chc",
  "taluk",
  "district",
  "clinic",
  "multispecialty",
  "superspecialty",
  "government",
];

export function facilityOptions(): { id: FacilityType; label: string }[] {
  return ALL_FACILITIES.map((id) => ({ id, label: FACILITY_LABELS[id] }));
}

function productRoleToDesk(roles: string[]): DeskRole {
  const set = new Set(roles.map((item) => item.toLowerCase()));
  if (set.has("admin")) return "admin";
  if (set.has("senior_clinician") || set.has("reviewer")) return "senior_clinician";
  if (set.has("resident")) return "resident";
  if (set.has("patient")) return "patient";
  return "staff";
}

function readStoredRole(): DeskRole {
  try {
    const raw = localStorage.getItem(ROLE_KEY);
    if (
      raw === "patient" ||
      raw === "staff" ||
      raw === "resident" ||
      raw === "senior_clinician" ||
      raw === "admin"
    ) {
      return raw;
    }
  } catch {
    /* ignore */
  }
  return "staff";
}

function readStoredFacility(): FacilityType {
  try {
    const raw = localStorage.getItem(FACILITY_KEY);
    if (raw && (ALL_FACILITIES as string[]).includes(raw)) {
      return raw as FacilityType;
    }
  } catch {
    /* ignore */
  }
  return "multispecialty";
}

function readMyPatientId(): string {
  try {
    const raw = localStorage.getItem(MY_PATIENT_KEY);
    if (raw && /^PAT-\d{6}$/.test(raw)) {
      return raw;
    }
  } catch {
    /* ignore */
  }
  return "PAT-000001";
}

function jwtRolesFor(role: DeskRole): string[] {
  if (role === "admin") {
    return ["admin"];
  }
  return [role];
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<DeskRole>(() => readStoredRole());
  const [facility, setFacilityState] = useState<FacilityType>(() => readStoredFacility());
  const [myPatientId, setMyPatientIdState] = useState<string>(() => readMyPatientId());
  const [demoSigninAllowed, setDemoSigninAllowed] = useState(true);
  const [authMode, setAuthMode] = useState("dev-jwt");
  const [signedInSubject, setSignedInSubject] = useState("");
  const [loadingAuth, setLoadingAuth] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const caps = await getAuthCapabilities();
        if (cancelled) return;
        setDemoSigninAllowed(caps.demo_signin_allowed);
        setAuthMode(caps.auth_mode || "unknown");
        if (!caps.demo_signin_allowed) {
          const me: AuthMe = await getAuthMe();
          if (cancelled) return;
          if (me.product_roles?.length) {
            const next = productRoleToDesk(me.product_roles);
            setRoleState(next);
            setAuthRoles(me.product_roles);
            if (me.patient_id) {
              setMyPatientIdState(me.patient_id);
              setAuthPatientId(me.patient_id);
            } else {
              setAuthPatientId(null);
            }
            setAuthOrgCode(me.org_code);
            setSignedInSubject(me.email || me.subject || "");
          }
        } else {
          setSignedInSubject("");
        }
      } catch {
        if (!cancelled) {
          setDemoSigninAllowed(true);
        }
      } finally {
        if (!cancelled) {
          setLoadingAuth(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!demoSigninAllowed) {
      return;
    }
    setAuthRoles(jwtRolesFor(role));
    setAuthPatientId(role === "patient" ? myPatientId : null);
    const org = FACILITY_ORG[facility] || "ORG-000001";
    setAuthOrgCode(role === "patient" || role === "admin" ? null : org);
  }, [role, myPatientId, facility, demoSigninAllowed]);

  const setRole = useCallback(
    (next: DeskRole) => {
      if (!demoSigninAllowed) {
        return;
      }
      setRoleState(next);
      try {
        localStorage.setItem(ROLE_KEY, next);
      } catch {
        /* ignore */
      }
      clearAuthToken();
      setAuthRoles(jwtRolesFor(next));
      setAuthPatientId(next === "patient" ? readMyPatientId() : null);
      const org = FACILITY_ORG[facility] || "ORG-000001";
      setAuthOrgCode(next === "patient" || next === "admin" ? null : org);
    },
    [demoSigninAllowed, facility],
  );

  const setFacility = useCallback(
    (next: FacilityType) => {
      setFacilityState(next);
      try {
        localStorage.setItem(FACILITY_KEY, next);
      } catch {
        /* ignore */
      }
      if (demoSigninAllowed && role !== "patient" && role !== "admin") {
        setAuthOrgCode(FACILITY_ORG[next] || "ORG-000001");
      }
    },
    [demoSigninAllowed, role],
  );

  const setMyPatientId = useCallback(
    (next: string) => {
      const id = next.trim().toUpperCase();
      if (!/^PAT-\d{6}$/.test(id)) {
        return;
      }
      setMyPatientIdState(id);
      try {
        localStorage.setItem(MY_PATIENT_KEY, id);
      } catch {
        /* ignore */
      }
      if (role === "patient" && demoSigninAllowed) {
        clearAuthToken();
        setAuthPatientId(id);
      }
    },
    [role, demoSigninAllowed],
  );

  const value = useMemo<RoleContextValue>(() => {
    const isPatient = role === "patient";
    const isSenior = role === "senior_clinician" || role === "admin";
    const isResident = role === "resident";
    const isStaff = role === "staff";
    const isAdmin = role === "admin";
    const canPrepare = !isPatient;
    const canDocument = true;
    const canCheckEvidence = !isPatient;
    const canAdjudicate = role === "senior_clinician" || role === "admin";

    return {
      role,
      setRole,
      facility,
      setFacility,
      myPatientId,
      setMyPatientId,
      isPatient,
      isSenior,
      isResident,
      isStaff,
      isAdmin,
      canPrepare,
      canDocument,
      canCheckEvidence,
      canAdjudicate,
      label: ROLE_LABELS[role],
      facilityLabel: FACILITY_LABELS[facility],
      demoSigninAllowed,
      authMode,
      signedInSubject,
      loadingAuth,
    };
  }, [
    role,
    facility,
    myPatientId,
    setRole,
    setFacility,
    setMyPatientId,
    demoSigninAllowed,
    authMode,
    signedInSubject,
    loadingAuth,
  ]);

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) {
    throw new Error("useRole must be used within RoleProvider");
  }
  return ctx;
}
