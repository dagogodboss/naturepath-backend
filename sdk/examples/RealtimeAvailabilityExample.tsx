/**
 * Real-time Availability Example
 * 
 * Demonstrates WebSocket-based live availability updates.
 */

import React, { useState, useMemo } from 'react';
import {
  usePractitioners,
  useRealtimeAvailability,
  useCreateBooking,
  useLockSlot,
  formatDate,
  addDays,
  type Practitioner,
  type AvailabilitySlot,
} from 'natural-path-sdk';

export function RealtimeAvailabilityExample() {
  const [selectedPractitioner, setSelectedPractitioner] = useState<Practitioner | null>(null);
  const [selectedDate, setSelectedDate] = useState(formatDate(new Date()));

  const { data: practitioners } = usePractitioners();

  // Generate next 7 days
  const availableDates = useMemo(
    () => Array.from({ length: 7 }, (_, i) => formatDate(addDays(new Date(), i))),
    []
  );

  return (
    <div className="realtime-example">
      <h1>Real-time Availability</h1>
      <p>Select a practitioner and date to see live availability updates.</p>

      {/* Practitioner Selection */}
      <section className="practitioner-selection">
        <h2>Select Practitioner</h2>
        <div className="practitioner-cards">
          {practitioners?.map((practitioner) => (
            <div
              key={practitioner.practitioner_id}
              className={`practitioner-card ${
                selectedPractitioner?.practitioner_id === practitioner.practitioner_id
                  ? 'selected'
                  : ''
              }`}
              onClick={() => setSelectedPractitioner(practitioner)}
            >
              <img
                src={practitioner.user?.profile_image_url || '/default-avatar.png'}
                alt={practitioner.user?.first_name}
              />
              <h3>
                {practitioner.user?.first_name} {practitioner.user?.last_name}
              </h3>
              <span className="rating">⭐ {practitioner.rating}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Date Selection */}
      {selectedPractitioner && (
        <section className="date-selection">
          <h2>Select Date</h2>
          <div className="date-tabs">
            {availableDates.map((date) => (
              <button
                key={date}
                className={`date-tab ${date === selectedDate ? 'active' : ''}`}
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
        </section>
      )}

      {/* Live Availability */}
      {selectedPractitioner && selectedDate && (
        <LiveAvailabilityGrid
          practitionerId={selectedPractitioner.practitioner_id}
          date={selectedDate}
        />
      )}
    </div>
  );
}

// ==================== Live Availability Grid ====================
interface LiveAvailabilityGridProps {
  practitionerId: string;
  date: string;
}

function LiveAvailabilityGrid({ practitionerId, date }: LiveAvailabilityGridProps) {
  const [selectedSlot, setSelectedSlot] = useState<string | null>(null);
  
  // WebSocket-powered real-time availability
  const { slots, isConnected, lastUpdate, error } = useRealtimeAvailability(
    practitionerId,
    date
  );

  // Mutations for booking
  const createBooking = useCreateBooking();
  const lockSlot = useLockSlot();

  const handleSlotClick = async (slot: AvailabilitySlot) => {
    if (slot.status !== 'available') return;

    setSelectedSlot(slot.slot_id);
    
    try {
      // This would normally be part of a larger booking flow
      // Here we just demonstrate the lock mechanism
      console.log('Selected slot:', slot);
    } catch (err) {
      console.error('Failed to select slot:', err);
    }
  };

  return (
    <section className="live-availability">
      {/* Connection Status */}
      <div className="connection-status">
        <span className={`indicator ${isConnected ? 'connected' : 'disconnected'}`}>
          {isConnected ? '🟢 Live' : '🔴 Connecting...'}
        </span>
        {lastUpdate && (
          <span className="last-update">
            Last updated: {lastUpdate.toLocaleTimeString()}
          </span>
        )}
      </div>

      {error && (
        <div className="error-message">
          Connection error. Availability may not be up to date.
        </div>
      )}

      {/* Legend */}
      <div className="legend">
        <span className="legend-item">
          <span className="dot available"></span> Available
        </span>
        <span className="legend-item">
          <span className="dot locked"></span> Held (being booked)
        </span>
        <span className="legend-item">
          <span className="dot booked"></span> Booked
        </span>
      </div>

      {/* Slots Grid */}
      <div className="slots-grid">
        {slots.length === 0 ? (
          <p className="no-slots">No available time slots for this date.</p>
        ) : (
          slots.map((slot) => (
            <SlotButton
              key={slot.slot_id}
              slot={slot}
              isSelected={slot.slot_id === selectedSlot}
              onClick={() => handleSlotClick(slot)}
            />
          ))
        )}
      </div>

      {/* Real-time update indicator */}
      <div className="realtime-note">
        <p>
          💡 This grid updates in real-time. When someone else locks or books a slot,
          you'll see it change immediately without refreshing the page.
        </p>
      </div>
    </section>
  );
}

// ==================== Slot Button ====================
interface SlotButtonProps {
  slot: AvailabilitySlot;
  isSelected: boolean;
  onClick: () => void;
}

function SlotButton({ slot, isSelected, onClick }: SlotButtonProps) {
  const getStatusIcon = () => {
    switch (slot.status) {
      case 'available':
        return '✓';
      case 'locked':
        return '⏳';
      case 'booked':
        return '✗';
      case 'blocked':
        return '🚫';
      default:
        return '';
    }
  };

  return (
    <button
      className={`slot-button ${slot.status} ${isSelected ? 'selected' : ''}`}
      disabled={slot.status !== 'available'}
      onClick={onClick}
      title={`${slot.start_time} - ${slot.end_time} (${slot.status})`}
    >
      <span className="time">{slot.start_time}</span>
      <span className="status-icon">{getStatusIcon()}</span>
    </button>
  );
}

// ==================== Styles (would be in CSS file) ====================
const styles = `
.realtime-example {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
}

.connection-status {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

.indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  font-size: 0.875rem;
}

.indicator.connected {
  background: #e6f7e6;
  color: #2e7d32;
}

.indicator.disconnected {
  background: #ffeaea;
  color: #d32f2f;
}

.slots-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 0.75rem;
  margin-top: 1rem;
}

.slot-button {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1rem;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
}

.slot-button.available {
  border-color: #4caf50;
  background: #e8f5e9;
}

.slot-button.available:hover {
  background: #c8e6c9;
  transform: scale(1.05);
}

.slot-button.locked {
  border-color: #ff9800;
  background: #fff3e0;
  cursor: not-allowed;
}

.slot-button.booked {
  border-color: #f44336;
  background: #ffebee;
  cursor: not-allowed;
}

.slot-button.selected {
  border-color: #2196f3;
  background: #e3f2fd;
  box-shadow: 0 0 0 3px rgba(33, 150, 243, 0.3);
}

.legend {
  display: flex;
  gap: 1.5rem;
  margin-bottom: 1rem;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.dot.available { background: #4caf50; }
.dot.locked { background: #ff9800; }
.dot.booked { background: #f44336; }

.realtime-note {
  margin-top: 2rem;
  padding: 1rem;
  background: #f5f5f5;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #666;
}
`;
