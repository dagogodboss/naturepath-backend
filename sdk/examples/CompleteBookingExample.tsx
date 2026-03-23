/**
 * Complete Booking Page Example
 * 
 * This example demonstrates the full booking flow using the SDK.
 */

import React, { useState } from 'react';
import {
  useServices,
  usePractitionersByService,
  useAvailability,
  useBookingFlow,
  useAuth,
  formatDate,
  formatCurrency,
  formatDuration,
  addDays,
  type Service,
  type Practitioner,
  type AvailabilitySlot,
} from '@natural-path/sdk';

type Step = 'service' | 'practitioner' | 'datetime' | 'confirm' | 'success';

export function CompleteBookingExample() {
  // Authentication check
  const { isAuthenticated, user } = useAuth();
  
  // Step management
  const [step, setStep] = useState<Step>('service');
  
  // Selected values
  const [selectedService, setSelectedService] = useState<Service | null>(null);
  const [selectedPractitioner, setSelectedPractitioner] = useState<Practitioner | null>(null);
  const [selectedDate, setSelectedDate] = useState(formatDate(new Date()));
  const [selectedSlot, setSelectedSlot] = useState<AvailabilitySlot | null>(null);
  const [notes, setNotes] = useState('');

  // Data fetching hooks
  const { data: services, isLoading: servicesLoading } = useServices();
  const { data: practitioners, isLoading: practitionersLoading } = usePractitionersByService(
    selectedService?.service_id
  );
  const { data: slots, isLoading: slotsLoading } = useAvailability(
    selectedPractitioner?.practitioner_id,
    selectedDate
  );

  // Booking flow hook
  const {
    initiateBooking,
    lockSlot,
    confirmBooking,
    booking,
    confirmationResponse,
    isLoading: bookingLoading,
    error: bookingError,
    reset: resetBooking,
  } = useBookingFlow();

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return (
      <div className="auth-required">
        <h2>Please log in to book an appointment</h2>
        <a href="/login">Go to Login</a>
      </div>
    );
  }

  // Step handlers
  const handleServiceSelect = (service: Service) => {
    setSelectedService(service);
    setSelectedPractitioner(null);
    setSelectedSlot(null);
    setStep('practitioner');
  };

  const handlePractitionerSelect = (practitioner: Practitioner) => {
    setSelectedPractitioner(practitioner);
    setSelectedSlot(null);
    setStep('datetime');
  };

  const handleSlotSelect = (slot: AvailabilitySlot) => {
    setSelectedSlot(slot);
    setStep('confirm');
  };

  const handleConfirm = async () => {
    if (!selectedService || !selectedPractitioner || !selectedSlot) return;

    try {
      // Step 1: Create draft booking
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

      // Step 2: Lock the slot (prevents double-booking)
      await lockSlot();

      // Step 3: Confirm and process payment
      await confirmBooking('card');

      // Success!
      setStep('success');
    } catch (err) {
      // Error is captured in bookingError
      console.error('Booking failed:', err);
    }
  };

  const handleStartOver = () => {
    resetBooking();
    setSelectedService(null);
    setSelectedPractitioner(null);
    setSelectedSlot(null);
    setNotes('');
    setStep('service');
  };

  // Generate available dates (next 14 days)
  const availableDates = Array.from({ length: 14 }, (_, i) =>
    formatDate(addDays(new Date(), i))
  );

  return (
    <div className="booking-container">
      {/* Progress Bar */}
      <div className="progress-bar">
        <div className={`step ${step === 'service' ? 'active' : ''}`}>Service</div>
        <div className={`step ${step === 'practitioner' ? 'active' : ''}`}>Practitioner</div>
        <div className={`step ${step === 'datetime' ? 'active' : ''}`}>Date & Time</div>
        <div className={`step ${step === 'confirm' ? 'active' : ''}`}>Confirm</div>
      </div>

      {/* Error Display */}
      {bookingError && (
        <div className="error-message">
          {bookingError.detail || 'Something went wrong. Please try again.'}
        </div>
      )}

      {/* Step 1: Service Selection */}
      {step === 'service' && (
        <div className="step-content">
          <h2>Select a Service</h2>
          {servicesLoading ? (
            <div className="loading">Loading services...</div>
          ) : (
            <div className="services-grid">
              {services?.map((service) => (
                <div
                  key={service.service_id}
                  className="service-card"
                  onClick={() => handleServiceSelect(service)}
                >
                  {service.image_url && (
                    <img src={service.image_url} alt={service.name} />
                  )}
                  <h3>{service.name}</h3>
                  <p>{service.description}</p>
                  <div className="service-meta">
                    <span className="price">
                      {service.discount_price
                        ? formatCurrency(service.discount_price)
                        : formatCurrency(service.price)}
                    </span>
                    <span className="duration">{formatDuration(service.duration_minutes)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Step 2: Practitioner Selection */}
      {step === 'practitioner' && (
        <div className="step-content">
          <button className="back-btn" onClick={() => setStep('service')}>
            ← Back
          </button>
          <h2>Choose Your Practitioner</h2>
          <p className="selected-service">
            Selected: <strong>{selectedService?.name}</strong>
          </p>
          {practitionersLoading ? (
            <div className="loading">Loading practitioners...</div>
          ) : (
            <div className="practitioners-grid">
              {practitioners?.map((practitioner) => (
                <div
                  key={practitioner.practitioner_id}
                  className="practitioner-card"
                  onClick={() => handlePractitionerSelect(practitioner)}
                >
                  <img
                    src={practitioner.user?.profile_image_url || '/default-avatar.png'}
                    alt={`${practitioner.user?.first_name} ${practitioner.user?.last_name}`}
                  />
                  <h3>
                    {practitioner.user?.first_name} {practitioner.user?.last_name}
                  </h3>
                  <p className="bio">{practitioner.bio.substring(0, 100)}...</p>
                  <div className="rating">
                    ⭐ {practitioner.rating} ({practitioner.total_reviews} reviews)
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Step 3: Date & Time Selection */}
      {step === 'datetime' && (
        <div className="step-content">
          <button className="back-btn" onClick={() => setStep('practitioner')}>
            ← Back
          </button>
          <h2>Select Date & Time</h2>

          {/* Date Selector */}
          <div className="date-selector">
            {availableDates.map((date) => (
              <button
                key={date}
                className={`date-btn ${date === selectedDate ? 'selected' : ''}`}
                onClick={() => setSelectedDate(date)}
              >
                {new Date(date).toLocaleDateString('en-US', {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </button>
            ))}
          </div>

          {/* Time Slots */}
          <h3>Available Times</h3>
          {slotsLoading ? (
            <div className="loading">Loading availability...</div>
          ) : slots && slots.length > 0 ? (
            <div className="slots-grid">
              {slots.map((slot) => (
                <button
                  key={slot.slot_id}
                  className={`slot-btn ${slot.status}`}
                  disabled={slot.status !== 'available'}
                  onClick={() => handleSlotSelect(slot)}
                >
                  {slot.start_time}
                  {slot.status === 'locked' && ' (held)'}
                  {slot.status === 'booked' && ' (booked)'}
                </button>
              ))}
            </div>
          ) : (
            <p>No available slots for this date. Please try another date.</p>
          )}
        </div>
      )}

      {/* Step 4: Confirmation */}
      {step === 'confirm' && (
        <div className="step-content">
          <button className="back-btn" onClick={() => setStep('datetime')}>
            ← Back
          </button>
          <h2>Confirm Your Booking</h2>

          <div className="booking-summary">
            <div className="summary-item">
              <span className="label">Service:</span>
              <span className="value">{selectedService?.name}</span>
            </div>
            <div className="summary-item">
              <span className="label">Practitioner:</span>
              <span className="value">
                {selectedPractitioner?.user?.first_name}{' '}
                {selectedPractitioner?.user?.last_name}
              </span>
            </div>
            <div className="summary-item">
              <span className="label">Date:</span>
              <span className="value">
                {new Date(selectedDate).toLocaleDateString('en-US', {
                  weekday: 'long',
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric',
                })}
              </span>
            </div>
            <div className="summary-item">
              <span className="label">Time:</span>
              <span className="value">
                {selectedSlot?.start_time} - {selectedSlot?.end_time}
              </span>
            </div>
            <div className="summary-item">
              <span className="label">Duration:</span>
              <span className="value">
                {formatDuration(selectedService?.duration_minutes || 0)}
              </span>
            </div>
            <div className="summary-item total">
              <span className="label">Total:</span>
              <span className="value">
                {formatCurrency(
                  selectedService?.discount_price || selectedService?.price || 0
                )}
              </span>
            </div>
          </div>

          {/* Notes */}
          <div className="notes-section">
            <label htmlFor="notes">Special Requests (optional):</label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Any special requests or notes for your appointment..."
              rows={3}
            />
          </div>

          {/* Customer Info */}
          <div className="customer-info">
            <h3>Booking for:</h3>
            <p>
              {user?.first_name} {user?.last_name}
            </p>
            <p>{user?.email}</p>
            {user?.phone && <p>{user?.phone}</p>}
          </div>

          <button
            className="confirm-btn"
            onClick={handleConfirm}
            disabled={bookingLoading}
          >
            {bookingLoading ? 'Processing...' : 'Confirm & Pay'}
          </button>
        </div>
      )}

      {/* Step 5: Success */}
      {step === 'success' && confirmationResponse && (
        <div className="step-content success">
          <div className="success-icon">✓</div>
          <h2>Booking Confirmed!</h2>
          <p>Your appointment has been successfully booked.</p>

          <div className="confirmation-details">
            <p>
              <strong>Booking ID:</strong>{' '}
              {confirmationResponse.booking_id.slice(0, 8).toUpperCase()}
            </p>
            <p>
              <strong>Date:</strong> {selectedDate}
            </p>
            <p>
              <strong>Time:</strong> {selectedSlot?.start_time}
            </p>
            <p>
              <strong>Service:</strong> {selectedService?.name}
            </p>
          </div>

          <p className="confirmation-note">
            A confirmation email has been sent to {user?.email}. Please arrive
            10-15 minutes before your appointment.
          </p>

          <div className="success-actions">
            <a href="/my-bookings" className="btn primary">
              View My Bookings
            </a>
            <button className="btn secondary" onClick={handleStartOver}>
              Book Another Appointment
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
