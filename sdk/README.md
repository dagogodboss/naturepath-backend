# natural-path-sdk

> React TypeScript SDK for The Natural Path Spa Management System

[![npm version](https://img.shields.io/npm/v/natural-path-sdk.svg)](https://www.npmjs.com/package/natural-path-sdk)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-blue.svg)](https://www.typescriptlang.org/)
[![React Query](https://img.shields.io/badge/React%20Query-5.0-ff4154.svg)](https://tanstack.com/query)

A fully-typed React SDK that provides hooks-based abstractions for the Natural Path Spa backend API. Built with React Query for optimal caching and state management.

**Registry:** [natural-path-sdk on npm](https://www.npmjs.com/package/natural-path-sdk) — latest **`1.0.0`**. Install with `npm install natural-path-sdk` (peer: `@tanstack/react-query`). The monorepo `frontend/` app uses **`"natural-path-sdk": "^1.0.0"`** from the registry so it matches what external consumers install.

## Features

- **Fully Typed** - Complete TypeScript support with all API types
- **React Query Integration** - Automatic caching, refetching, and optimistic updates
- **Auth Management** - JWT handling with automatic token refresh
- **Real-time Updates** - WebSocket support for live availability updates
- **Complete Booking Flow** - Multi-step booking with slot locking
- **Admin Dashboard** - Stats, analytics, and user management hooks

## Publishing (maintainers)

The repo includes [`.github/workflows/publish-sdk.yml`](../../.github/workflows/publish-sdk.yml).

1. **npm (recommended for frontend consumers)**  
   **Cost:** Publishing **public** packages is **free**; you only need a free [npmjs.com](https://www.npmjs.com) account. Paid npm plans are for **private** packages and org features you may not need.  
   **Token:** GitHub → repo **Settings → Secrets → Actions** → add `NPM_TOKEN`. Create the token at [npm → Access Tokens](https://www.npmjs.com/settings/~/tokens) (sign in → **Generate New Token**). Use type **Automation** (classic) or a fine-grained token with permission to publish the `natural-path-sdk` package. The workflow uses it as `NODE_AUTH_TOKEN` during `npm publish` — you do **not** paste the token into the repo; only into GitHub Secrets.  
   **Scope:** This package is published as **`natural-path-sdk`** (unscoped), so you do **not** need an npm org or `@scope` — only an account that is allowed to publish that name (first publish wins the name). Bump `version` in `backend/sdk/package.json`, merge, then either:
   - **Local (token only in your shell):** `export NODE_AUTH_TOKEN=…` then run [`../scripts/publish-sdk-to-npm.sh`](../scripts/publish-sdk-to-npm.sh) from the monorepo (script lives under `backend/scripts/`).
   - **Actions → Publish SDK → Run workflow** → choose **npm**, or  
   - Push a git tag `sdk/v1.0.1` (must match the version you intend to publish).

2. **GitHub Packages**  
   Not configured for this package name (GPR works best with scoped `@org/pkg`). Use npm only unless you later rename to a scoped package.

**Local SDK development (monorepo):** To test unpublished SDK changes in `frontend/`, use either `npm link` (`cd backend/sdk && npm link` then `cd frontend && npm link natural-path-sdk`) or temporarily set `"natural-path-sdk": "file:../backend/sdk"` and add a Vite alias to `../backend/sdk/src/index.ts` — revert before shipping so the app tracks the published package.

## Installation

```bash
npm install natural-path-sdk @tanstack/react-query
# or
yarn add natural-path-sdk @tanstack/react-query
# or
pnpm add natural-path-sdk @tanstack/react-query
```

## Quick Start

### 1. Wrap your app with the provider

```tsx
import { NaturalPathProvider } from 'natural-path-sdk';

function App() {
  return (
    <NaturalPathProvider 
      baseUrl="https://api.thenaturalpath.com"
      onAuthError={(error) => {
        console.error('Auth error:', error);
        // Redirect to login page
      }}
    >
      <YourApp />
    </NaturalPathProvider>
  );
}
```

### 2. Use hooks in your components

```tsx
import { useServices, useAuth, useBookingFlow } from 'natural-path-sdk';

function ServicesPage() {
  const { data: services, isLoading } = useServices();

  if (isLoading) return <div>Loading...</div>;

  return (
    <div>
      {services?.map(service => (
        <ServiceCard key={service.service_id} service={service} />
      ))}
    </div>
  );
}
```

## Authentication

### Login

```tsx
import { useAuth } from 'natural-path-sdk';

function LoginPage() {
  const { login, isLoading, error } = useAuth();

  const handleSubmit = async (email: string, password: string) => {
    try {
      await login({ email, password });
      // Redirect to dashboard
    } catch (err) {
      // Handle error
    }
  };

  return (
    <form onSubmit={...}>
      {/* Your form fields */}
    </form>
  );
}
```

### Register

```tsx
const { register } = useAuth();

await register({
  email: 'user@example.com',
  password: 'securepassword',
  first_name: 'John',
  last_name: 'Doe',
  phone: '+1234567890'
});
```

### Check Auth State

```tsx
const { user, isAuthenticated, logout } = useAuth();

if (isAuthenticated) {
  return (
    <div>
      Welcome, {user?.first_name}!
      <button onClick={logout}>Logout</button>
    </div>
  );
}
```

## Services

### List Services

```tsx
import { useServices, useFeaturedServices } from 'natural-path-sdk';

// All services
const { data: services } = useServices();

// Featured services only
const { data: featured } = useFeaturedServices();

// By category
const { data: massages } = useServices('massage');
```

### Get Single Service

```tsx
import { useService } from 'natural-path-sdk';

const { data: service } = useService('service-id');
```

## Practitioners

### List Practitioners

```tsx
import { 
  usePractitioners, 
  useFeaturedPractitioners,
  usePractitionersByService 
} from 'natural-path-sdk';

// All practitioners
const { data: practitioners } = usePractitioners();

// Featured only
const { data: featured } = useFeaturedPractitioners();

// By service
const { data: massageTherapists } = usePractitionersByService('massage-service-id');
```

### Get Availability

```tsx
import { useAvailability } from 'natural-path-sdk';

const { data: slots, isLoading } = useAvailability(
  'practitioner-id',
  '2026-03-25'  // YYYY-MM-DD format
);

// Slots automatically refresh every 30 seconds
```

### Real-time Availability (WebSocket)

```tsx
import { useRealtimeAvailability } from 'natural-path-sdk';

function AvailabilityCalendar({ practitionerId, date }) {
  const { slots, isConnected, lastUpdate } = useRealtimeAvailability(
    practitionerId,
    date
  );

  return (
    <div>
      {isConnected && <span>Live updates enabled</span>}
      {slots.map(slot => (
        <TimeSlot 
          key={slot.slot_id} 
          slot={slot}
          disabled={slot.status !== 'available'}
        />
      ))}
    </div>
  );
}
```

## Booking Flow

The SDK provides a complete multi-step booking flow:

### Step-by-Step Approach

```tsx
import { useCreateBooking, useLockSlot, useConfirmBooking } from 'natural-path-sdk';

function BookingPage() {
  const createBooking = useCreateBooking();
  const lockSlot = useLockSlot();
  const confirmBooking = useConfirmBooking();

  // Step 1: Initiate booking
  const handleSelectSlot = async () => {
    const booking = await createBooking.mutateAsync({
      service_id: 'service-id',
      practitioner_id: 'practitioner-id',
      slot: {
        date: '2026-03-25',
        start_time: '10:00',
        end_time: '11:00'
      },
      notes: 'First time customer'
    });
    
    // Step 2: Lock the slot (5 min hold)
    await lockSlot.mutateAsync(booking.booking_id);
    
    // Step 3: Confirm and pay
    const confirmed = await confirmBooking.mutateAsync({
      booking_id: booking.booking_id,
      payment_method: 'card'
    });
  };
}
```

### Combined Flow Hook (Recommended)

```tsx
import { useBookingFlow } from 'natural-path-sdk';

function BookingWizard() {
  const {
    initiateBooking,
    lockSlot,
    confirmBooking,
    currentStep,
    bookingId,
    booking,
    isLoading,
    error,
    reset
  } = useBookingFlow();

  const handleBook = async () => {
    // Step 1: Initiate
    await initiateBooking({
      service_id: selectedService,
      practitioner_id: selectedPractitioner,
      slot: selectedSlot
    });

    // Step 2: Lock slot
    await lockSlot();

    // Step 3: Confirm with payment
    await confirmBooking('card');
  };

  return (
    <div>
      <p>Current step: {currentStep}</p>
      {isLoading && <Spinner />}
      {error && <ErrorMessage error={error} />}
      <button onClick={handleBook}>Complete Booking</button>
    </div>
  );
}
```

### Cancel Booking

```tsx
import { useCancelBooking } from 'natural-path-sdk';

const { mutate: cancelBooking } = useCancelBooking();

cancelBooking({
  booking_id: 'booking-id',
  reason: 'Schedule conflict'
});
```

## User Profile

```tsx
import { useProfile, useUpdateProfile, useUserBookings } from 'natural-path-sdk';

function ProfilePage() {
  const { data: profile } = useProfile();
  const { mutate: updateProfile } = useUpdateProfile();
  const { data: myBookings } = useUserBookings();

  const handleUpdate = () => {
    updateProfile({
      phone: '+1234567890',
      first_name: 'Updated Name'
    });
  };

  return (
    <div>
      <h1>{profile?.first_name} {profile?.last_name}</h1>
      <h2>My Bookings</h2>
      {myBookings?.map(booking => (
        <BookingCard key={booking.booking_id} booking={booking} />
      ))}
    </div>
  );
}
```

## Notifications

```tsx
import { useNotifications, useMarkNotificationRead } from 'natural-path-sdk';

function NotificationsPanel() {
  const { data: notifications } = useNotifications();
  const { mutate: markAsRead } = useMarkNotificationRead();

  return (
    <div>
      {notifications?.map(notif => (
        <div 
          key={notif.notification_id}
          onClick={() => markAsRead(notif.notification_id)}
        >
          <h4>{notif.title}</h4>
          <p>{notif.message}</p>
        </div>
      ))}
    </div>
  );
}
```

### Real-time Notifications (WebSocket)

```tsx
import { useRealtimeNotifications } from 'natural-path-sdk';

function App() {
  const { isConnected } = useRealtimeNotifications(
    userId,
    (notification) => {
      // Show toast notification
      toast.info(notification.title);
    }
  );
}
```

## Admin Dashboard

### Dashboard Stats

```tsx
import { useAdminStats } from 'natural-path-sdk';

function AdminDashboard() {
  const { data: stats } = useAdminStats();

  return (
    <div>
      <StatCard title="Total Customers" value={stats?.total_customers} />
      <StatCard title="Today's Revenue" value={stats?.revenue_today} />
      <StatCard title="Bookings Today" value={stats?.bookings_today} />
    </div>
  );
}
```

### Booking Analytics

```tsx
import { useBookingAnalytics } from 'natural-path-sdk';

const { data: weeklyAnalytics } = useBookingAnalytics('week');
const { data: monthlyAnalytics } = useBookingAnalytics('month');
```

### User Management

```tsx
import { useUsers, useUpdateUserRole, useUpdateUserStatus } from 'natural-path-sdk';

function UserManagement() {
  const { data: users } = useUsers();
  const { mutate: updateRole } = useUpdateUserRole();
  const { mutate: updateStatus } = useUpdateUserStatus();

  const makeAdmin = (userId: string) => {
    updateRole({ userId, role: 'admin' });
  };

  const deactivateUser = (userId: string) => {
    updateStatus({ userId, isActive: false });
  };
}
```

## Utilities

```tsx
import { 
  formatDate, 
  formatCurrency, 
  formatDuration,
  getWeekRange 
} from 'natural-path-sdk';

formatDate(new Date());        // '2026-03-25'
formatCurrency(150);           // '$150.00'
formatDuration(90);            // '1 hr 30 min'
getWeekRange();                // { start: '2026-03-23', end: '2026-03-29' }
```

## Advanced Usage

### Custom Query Client

```tsx
import { NaturalPathProvider, QueryClient } from 'natural-path-sdk';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10 * 60 * 1000, // 10 minutes
    },
  },
});

<NaturalPathProvider baseUrl="..." queryClient={queryClient}>
  <App />
</NaturalPathProvider>
```

### Custom Token Storage

```tsx
import { NaturalPathProvider } from 'natural-path-sdk';

const secureStorage = {
  getAccessToken: () => secureStore.get('access_token'),
  getRefreshToken: () => secureStore.get('refresh_token'),
  setTokens: (access, refresh) => {
    secureStore.set('access_token', access);
    secureStore.set('refresh_token', refresh);
  },
  clearTokens: () => {
    secureStore.delete('access_token');
    secureStore.delete('refresh_token');
  },
};

<NaturalPathProvider baseUrl="..." tokenStorage={secureStorage}>
  <App />
</NaturalPathProvider>
```

### Direct API Access

```tsx
import { servicesApi, getApiClient } from 'natural-path-sdk';

// Use pre-built API methods
const services = await servicesApi.getAll();

// Or use the axios client directly
const client = getApiClient();
const response = await client.get('/api/custom-endpoint');
```

### Manual Cache Invalidation

```tsx
import { useQueryClient, queryKeys } from 'natural-path-sdk';

function RefreshButton() {
  const queryClient = useQueryClient();

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.services.all });
  };

  return <button onClick={refresh}>Refresh Services</button>;
}
```

## TypeScript Support

All types are exported:

```tsx
import type { 
  Service, 
  Practitioner, 
  Booking, 
  User,
  AvailabilitySlot 
} from 'natural-path-sdk';

interface ServiceCardProps {
  service: Service;
}
```

## API Reference

### Hooks

| Hook | Description |
|------|-------------|
| `useAuth()` | Authentication state and methods |
| `useServices()` | Fetch all services |
| `useFeaturedServices()` | Fetch featured services |
| `useService(id)` | Fetch single service |
| `usePractitioners()` | Fetch all practitioners |
| `usePractitioner(id)` | Fetch single practitioner |
| `useAvailability(id, date)` | Fetch availability slots |
| `useBookingFlow()` | Complete booking flow |
| `useUserBookings()` | User's bookings |
| `useProfile()` | User profile |
| `useAdminStats()` | Admin dashboard stats |
| `useRealtimeAvailability(id, date)` | WebSocket availability |

## License

MIT
