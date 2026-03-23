# Integration Guide

## Complete Setup Guide for Frontend Engineers

This guide walks you through integrating the `@natural-path/sdk` into your React TypeScript application.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Basic Setup](#basic-setup)
4. [Authentication](#authentication)
5. [Fetching Data](#fetching-data)
6. [Booking Flow](#booking-flow)
7. [Real-time Features](#real-time-features)
8. [Error Handling](#error-handling)
9. [Caching Strategy](#caching-strategy)
10. [Best Practices](#best-practices)

---

## Prerequisites

- React 17+ or 18+
- TypeScript 4.7+
- Node.js 16+

**Peer Dependencies:**
```json
{
  "react": ">=17.0.0",
  "react-dom": ">=17.0.0",
  "@tanstack/react-query": ">=5.0.0"
}
```

---

## Installation

```bash
# Using npm
npm install @natural-path/sdk @tanstack/react-query

# Using yarn
yarn add @natural-path/sdk @tanstack/react-query

# Using pnpm
pnpm add @natural-path/sdk @tanstack/react-query
```

---

## Basic Setup

### 1. Configure the Provider

Wrap your application with `NaturalPathProvider`:

```tsx
// src/App.tsx
import React from 'react';
import { NaturalPathProvider } from '@natural-path/sdk';
import { Router } from './Router';

const API_URL = process.env.REACT_APP_API_URL || 'https://api.thenaturalpath.com';

function App() {
  return (
    <NaturalPathProvider 
      baseUrl={API_URL}
      onAuthError={(error) => {
        // Handle authentication errors globally
        console.error('Authentication error:', error.detail);
        
        // Redirect to login page
        window.location.href = '/login';
      }}
    >
      <Router />
    </NaturalPathProvider>
  );
}

export default App;
```

### 2. Environment Variables

Create a `.env` file:

```env
REACT_APP_API_URL=https://api.thenaturalpath.com
```

---

## Authentication

### Login Flow

```tsx
// src/pages/LoginPage.tsx
import React, { useState } from 'react';
import { useAuth } from '@natural-path/sdk';
import { useNavigate } from 'react-router-dom';

export function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { login, isLoading, error } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    try {
      await login({ email, password });
      navigate('/dashboard');
    } catch (err) {
      // Error is already captured in the error state
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        required
      />
      
      {error && <div className="error">{error.message}</div>}
      
      <button type="submit" disabled={isLoading}>
        {isLoading ? 'Logging in...' : 'Login'}
      </button>
    </form>
  );
}
```

### Registration Flow

```tsx
// src/pages/RegisterPage.tsx
import React, { useState } from 'react';
import { useAuth, type RegisterRequest } from '@natural-path/sdk';

export function RegisterPage() {
  const { register, isLoading, error } = useAuth();
  const [formData, setFormData] = useState<RegisterRequest>({
    email: '',
    password: '',
    first_name: '',
    last_name: '',
    phone: '',
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    try {
      await register(formData);
      // User is now logged in and redirected
    } catch (err) {
      // Handle error
    }
  };

  // Form implementation...
}
```

### Protected Routes

```tsx
// src/components/ProtectedRoute.tsx
import { useAuth } from '@natural-path/sdk';
import { Navigate, Outlet } from 'react-router-dom';

export function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
```

### Admin-Only Routes

```tsx
// src/components/AdminRoute.tsx
import { useAuth } from '@natural-path/sdk';
import { Navigate, Outlet } from 'react-router-dom';

export function AdminRoute() {
  const { user, isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated || user?.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
```

---

## Fetching Data

### Services Page Example

```tsx
// src/pages/ServicesPage.tsx
import React from 'react';
import { useServices, useFeaturedServices, type Service } from '@natural-path/sdk';

export function ServicesPage() {
  const { data: services, isLoading, error } = useServices();
  const { data: featured } = useFeaturedServices();

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return <ErrorMessage message={error.detail} />;
  }

  return (
    <div>
      {/* Featured Section */}
      <section>
        <h2>Featured Services</h2>
        <div className="grid">
          {featured?.map((service) => (
            <ServiceCard key={service.service_id} service={service} featured />
          ))}
        </div>
      </section>

      {/* All Services */}
      <section>
        <h2>All Services</h2>
        <div className="grid">
          {services?.map((service) => (
            <ServiceCard key={service.service_id} service={service} />
          ))}
        </div>
      </section>
    </div>
  );
}

interface ServiceCardProps {
  service: Service;
  featured?: boolean;
}

function ServiceCard({ service, featured }: ServiceCardProps) {
  return (
    <div className={`card ${featured ? 'featured' : ''}`}>
      {service.image_url && (
        <img src={service.image_url} alt={service.name} />
      )}
      <h3>{service.name}</h3>
      <p>{service.description}</p>
      <div className="price">
        {service.discount_price ? (
          <>
            <span className="original">${service.price}</span>
            <span className="discounted">${service.discount_price}</span>
          </>
        ) : (
          <span>${service.price}</span>
        )}
      </div>
      <span className="duration">{service.duration_minutes} min</span>
    </div>
  );
}
```

### Practitioners with Availability

```tsx
// src/pages/PractitionerPage.tsx
import React, { useState } from 'react';
import { 
  usePractitioner, 
  useAvailability,
  formatDate,
  addDays,
  type AvailabilitySlot 
} from '@natural-path/sdk';

interface Props {
  practitionerId: string;
}

export function PractitionerPage({ practitionerId }: Props) {
  const [selectedDate, setSelectedDate] = useState(formatDate(new Date()));
  const { data: practitioner, isLoading } = usePractitioner(practitionerId);
  const { data: slots } = useAvailability(practitionerId, selectedDate);

  // Generate next 7 days
  const dates = Array.from({ length: 7 }, (_, i) => 
    formatDate(addDays(new Date(), i))
  );

  if (isLoading) return <LoadingSpinner />;

  return (
    <div>
      <div className="practitioner-header">
        <img src={practitioner?.user?.profile_image_url} alt="" />
        <h1>
          {practitioner?.user?.first_name} {practitioner?.user?.last_name}
        </h1>
        <p>{practitioner?.bio}</p>
        <div className="rating">
          ⭐ {practitioner?.rating} ({practitioner?.total_reviews} reviews)
        </div>
      </div>

      {/* Date Selector */}
      <div className="date-tabs">
        {dates.map((date) => (
          <button
            key={date}
            className={date === selectedDate ? 'active' : ''}
            onClick={() => setSelectedDate(date)}
          >
            {new Date(date).toLocaleDateString('en-US', { 
              weekday: 'short', 
              month: 'short', 
              day: 'numeric' 
            })}
          </button>
        ))}
      </div>

      {/* Time Slots */}
      <div className="time-slots">
        {slots?.map((slot) => (
          <TimeSlotButton key={slot.slot_id} slot={slot} />
        ))}
        {slots?.length === 0 && (
          <p>No available slots for this date.</p>
        )}
      </div>
    </div>
  );
}

function TimeSlotButton({ slot }: { slot: AvailabilitySlot }) {
  const isAvailable = slot.status === 'available';
  
  return (
    <button 
      className={`slot ${slot.status}`}
      disabled={!isAvailable}
    >
      {slot.start_time}
    </button>
  );
}
```

---

## Booking Flow

### Complete Booking Component

```tsx
// src/pages/BookingPage.tsx
import React, { useState } from 'react';
import { 
  useServices,
  usePractitionersByService,
  useAvailability,
  useBookingFlow,
  formatDate,
  formatCurrency,
  type Service,
  type Practitioner,
  type AvailabilitySlot,
} from '@natural-path/sdk';

type BookingStep = 'service' | 'practitioner' | 'datetime' | 'confirm' | 'success';

export function BookingPage() {
  const [step, setStep] = useState<BookingStep>('service');
  const [selectedService, setSelectedService] = useState<Service | null>(null);
  const [selectedPractitioner, setSelectedPractitioner] = useState<Practitioner | null>(null);
  const [selectedDate, setSelectedDate] = useState(formatDate(new Date()));
  const [selectedSlot, setSelectedSlot] = useState<AvailabilitySlot | null>(null);
  const [notes, setNotes] = useState('');

  const { data: services } = useServices();
  const { data: practitioners } = usePractitionersByService(selectedService?.service_id);
  const { data: slots } = useAvailability(selectedPractitioner?.practitioner_id, selectedDate);
  
  const {
    initiateBooking,
    lockSlot,
    confirmBooking,
    booking,
    isLoading,
    error,
    reset,
  } = useBookingFlow();

  const handleSelectService = (service: Service) => {
    setSelectedService(service);
    setStep('practitioner');
  };

  const handleSelectPractitioner = (practitioner: Practitioner) => {
    setSelectedPractitioner(practitioner);
    setStep('datetime');
  };

  const handleSelectSlot = (slot: AvailabilitySlot) => {
    setSelectedSlot(slot);
    setStep('confirm');
  };

  const handleConfirmBooking = async () => {
    if (!selectedService || !selectedPractitioner || !selectedSlot) return;

    try {
      // Step 1: Initiate
      await initiateBooking({
        service_id: selectedService.service_id,
        practitioner_id: selectedPractitioner.practitioner_id,
        slot: {
          date: selectedDate,
          start_time: selectedSlot.start_time,
          end_time: selectedSlot.end_time,
        },
        notes: notes || undefined,
      });

      // Step 2: Lock slot (5 min hold)
      await lockSlot();

      // Step 3: Confirm and pay
      await confirmBooking('card');

      setStep('success');
    } catch (err) {
      // Error is handled by the hook
    }
  };

  const handleStartOver = () => {
    reset();
    setSelectedService(null);
    setSelectedPractitioner(null);
    setSelectedSlot(null);
    setNotes('');
    setStep('service');
  };

  return (
    <div className="booking-wizard">
      {/* Progress Indicator */}
      <ProgressBar currentStep={step} />

      {/* Error Display */}
      {error && (
        <div className="error-banner">
          {error.detail || 'An error occurred. Please try again.'}
        </div>
      )}

      {/* Step Content */}
      {step === 'service' && (
        <ServiceSelection 
          services={services || []} 
          onSelect={handleSelectService} 
        />
      )}

      {step === 'practitioner' && (
        <PractitionerSelection
          practitioners={practitioners || []}
          service={selectedService!}
          onSelect={handleSelectPractitioner}
          onBack={() => setStep('service')}
        />
      )}

      {step === 'datetime' && (
        <DateTimeSelection
          slots={slots || []}
          selectedDate={selectedDate}
          onDateChange={setSelectedDate}
          onSelect={handleSelectSlot}
          onBack={() => setStep('practitioner')}
        />
      )}

      {step === 'confirm' && (
        <ConfirmationStep
          service={selectedService!}
          practitioner={selectedPractitioner!}
          slot={selectedSlot!}
          date={selectedDate}
          notes={notes}
          onNotesChange={setNotes}
          onConfirm={handleConfirmBooking}
          onBack={() => setStep('datetime')}
          isLoading={isLoading}
        />
      )}

      {step === 'success' && (
        <SuccessStep
          booking={booking!}
          onNewBooking={handleStartOver}
        />
      )}
    </div>
  );
}
```

---

## Real-time Features

### Live Availability Updates

```tsx
// src/components/LiveAvailability.tsx
import React from 'react';
import { useRealtimeAvailability } from '@natural-path/sdk';

interface Props {
  practitionerId: string;
  date: string;
  onSlotSelect: (slotId: string) => void;
}

export function LiveAvailability({ practitionerId, date, onSlotSelect }: Props) {
  const { slots, isConnected, lastUpdate } = useRealtimeAvailability(
    practitionerId,
    date
  );

  return (
    <div>
      {/* Connection Status */}
      <div className={`status ${isConnected ? 'connected' : 'disconnected'}`}>
        {isConnected ? '🟢 Live' : '🔴 Reconnecting...'}
        {lastUpdate && (
          <span>Last updated: {lastUpdate.toLocaleTimeString()}</span>
        )}
      </div>

      {/* Slots Grid */}
      <div className="slots-grid">
        {slots.map((slot) => (
          <button
            key={slot.slot_id}
            className={`slot ${slot.status}`}
            disabled={slot.status !== 'available'}
            onClick={() => onSlotSelect(slot.slot_id)}
          >
            <span className="time">{slot.start_time}</span>
            <span className="status-indicator">
              {slot.status === 'available' && '✓'}
              {slot.status === 'locked' && '⏳'}
              {slot.status === 'booked' && '✗'}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

### Real-time Notifications

```tsx
// src/components/NotificationListener.tsx
import { useRealtimeNotifications } from '@natural-path/sdk';
import { toast } from 'react-toastify'; // or your preferred toast library

interface Props {
  userId: string;
}

export function NotificationListener({ userId }: Props) {
  const { isConnected } = useRealtimeNotifications(userId, (notification) => {
    // Show toast when notification arrives
    toast.info(notification.title, {
      onClick: () => {
        // Handle notification click
        window.location.href = `/notifications`;
      },
    });
  });

  // This component doesn't render anything visible
  return null;
}
```

---

## Error Handling

### Global Error Boundary

```tsx
// src/components/ErrorBoundary.tsx
import React, { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-page">
          <h1>Something went wrong</h1>
          <p>{this.state.error?.message}</p>
          <button onClick={() => window.location.reload()}>
            Reload Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
```

### Query Error Handling

```tsx
import { useServices } from '@natural-path/sdk';

function ServicesPage() {
  const { data, error, isError, refetch } = useServices();

  if (isError) {
    return (
      <div className="error">
        <p>Failed to load services: {error?.detail}</p>
        <button onClick={() => refetch()}>Try Again</button>
      </div>
    );
  }

  // Render services...
}
```

### Mutation Error Handling

```tsx
import { useCreateBooking } from '@natural-path/sdk';
import { useState } from 'react';

function BookingForm() {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const { mutate, isPending } = useCreateBooking();

  const handleSubmit = () => {
    setErrorMessage(null);
    
    mutate(bookingData, {
      onError: (error) => {
        setErrorMessage(error.detail || 'Booking failed. Please try again.');
      },
      onSuccess: () => {
        // Handle success
      },
    });
  };

  return (
    <div>
      {errorMessage && <Alert type="error">{errorMessage}</Alert>}
      <button onClick={handleSubmit} disabled={isPending}>
        {isPending ? 'Booking...' : 'Book Now'}
      </button>
    </div>
  );
}
```

---

## Caching Strategy

### Understanding Default Cache Times

| Data Type | Stale Time | Refetch Interval |
|-----------|------------|------------------|
| Services | 5 minutes | - |
| Practitioners | 5 minutes | - |
| Availability | 1 minute | 30 seconds |
| User Profile | 5 minutes | - |
| Notifications | 30 seconds | 1 minute |
| Admin Stats | 1 minute | 5 minutes |

### Manual Cache Invalidation

```tsx
import { useQueryClient, queryKeys } from '@natural-path/sdk';

function AdminActions() {
  const queryClient = useQueryClient();

  const refreshServices = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.services.all });
  };

  const refreshAllData = () => {
    queryClient.invalidateQueries(); // Invalidate everything
  };

  const clearCache = () => {
    queryClient.clear(); // Remove all cached data
  };
}
```

### Prefetching Data

```tsx
import { useQueryClient, servicesApi, queryKeys } from '@natural-path/sdk';

function HomePage() {
  const queryClient = useQueryClient();

  // Prefetch services on hover
  const prefetchServices = () => {
    queryClient.prefetchQuery({
      queryKey: queryKeys.services.all,
      queryFn: () => servicesApi.getAll(),
    });
  };

  return (
    <a 
      href="/services" 
      onMouseEnter={prefetchServices}
    >
      View Services
    </a>
  );
}
```

---

## Best Practices

### 1. Type Your Props

```tsx
import type { Service, Practitioner } from '@natural-path/sdk';

interface ServiceCardProps {
  service: Service;
  onSelect?: (service: Service) => void;
}
```

### 2. Handle Loading States

```tsx
function Component() {
  const { data, isLoading, isFetching } = useServices();

  // isLoading = first load (no cached data)
  // isFetching = any fetch (including background refetch)

  if (isLoading) {
    return <Skeleton />; // Full loading state
  }

  return (
    <div>
      {isFetching && <SmallSpinner />} {/* Background refresh indicator */}
      {/* Content */}
    </div>
  );
}
```

### 3. Use Suspense (React 18+)

```tsx
import { Suspense } from 'react';

function App() {
  return (
    <Suspense fallback={<LoadingPage />}>
      <ServicesPage />
    </Suspense>
  );
}
```

### 4. Optimistic Updates

```tsx
import { useQueryClient, useCancelBooking, queryKeys } from '@natural-path/sdk';

function BookingActions({ booking }) {
  const queryClient = useQueryClient();
  const { mutate } = useCancelBooking();

  const handleCancel = () => {
    // Optimistically update the UI
    queryClient.setQueryData(
      queryKeys.bookings.detail(booking.booking_id),
      { ...booking, status: 'cancelled' }
    );

    mutate({ booking_id: booking.booking_id }, {
      onError: () => {
        // Revert on error
        queryClient.setQueryData(
          queryKeys.bookings.detail(booking.booking_id),
          booking
        );
      },
    });
  };
}
```

---

## Troubleshooting

### Common Issues

**1. "SDK not initialized" error**
- Ensure `NaturalPathProvider` wraps your entire app
- Check that `baseUrl` is correctly set

**2. 401 Unauthorized errors**
- Check if tokens are being stored correctly
- Verify the `onAuthError` callback is set up

**3. WebSocket not connecting**
- Ensure backend WebSocket endpoints are accessible
- Check browser console for connection errors

**4. Stale data**
- Use `queryClient.invalidateQueries()` after mutations
- Adjust `staleTime` for more frequent updates

---

## Support

- GitHub Issues: [github.com/natural-path/sdk/issues](https://github.com/natural-path/sdk/issues)
- Documentation: [docs.thenaturalpath.com](https://docs.thenaturalpath.com)
