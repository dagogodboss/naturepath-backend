/**
 * Admin Dashboard Example
 * 
 * This example shows how to build an admin dashboard using the SDK.
 */

import React, { useState } from 'react';
import {
  useAdminStats,
  useBookingAnalytics,
  useAllBookings,
  useUsers,
  useUpdateUserRole,
  useUpdateUserStatus,
  useAdminCancelBooking,
  formatCurrency,
  type User,
  type Booking,
  type BookingStatus,
  type UserRole,
} from '@natural-path/sdk';

export function AdminDashboardExample() {
  return (
    <div className="admin-dashboard">
      <h1>Admin Dashboard</h1>
      
      <StatsOverview />
      <AnalyticsSection />
      <BookingsManagement />
      <UserManagement />
    </div>
  );
}

// ==================== Stats Overview ====================
function StatsOverview() {
  const { data: stats, isLoading, error } = useAdminStats();

  if (isLoading) return <div className="loading">Loading stats...</div>;
  if (error) return <div className="error">Failed to load stats</div>;

  return (
    <div className="stats-grid">
      <StatCard
        title="Total Customers"
        value={stats?.total_customers || 0}
        icon="👥"
      />
      <StatCard
        title="Total Practitioners"
        value={stats?.total_practitioners || 0}
        icon="💆"
      />
      <StatCard
        title="Bookings Today"
        value={stats?.bookings_today || 0}
        icon="📅"
      />
      <StatCard
        title="Revenue Today"
        value={formatCurrency(stats?.revenue_today || 0)}
        icon="💰"
      />
      <StatCard
        title="This Week"
        value={formatCurrency(stats?.revenue_this_week || 0)}
        icon="📊"
      />
      <StatCard
        title="This Month"
        value={formatCurrency(stats?.revenue_this_month || 0)}
        icon="📈"
      />
    </div>
  );
}

function StatCard({ title, value, icon }: { title: string; value: string | number; icon: string }) {
  return (
    <div className="stat-card">
      <span className="icon">{icon}</span>
      <div className="content">
        <span className="value">{value}</span>
        <span className="title">{title}</span>
      </div>
    </div>
  );
}

// ==================== Analytics Section ====================
function AnalyticsSection() {
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week');
  const { data: analytics, isLoading } = useBookingAnalytics(period);

  if (isLoading) return <div className="loading">Loading analytics...</div>;

  return (
    <section className="analytics-section">
      <div className="section-header">
        <h2>Booking Analytics</h2>
        <div className="period-selector">
          <button
            className={period === 'day' ? 'active' : ''}
            onClick={() => setPeriod('day')}
          >
            Today
          </button>
          <button
            className={period === 'week' ? 'active' : ''}
            onClick={() => setPeriod('week')}
          >
            This Week
          </button>
          <button
            className={period === 'month' ? 'active' : ''}
            onClick={() => setPeriod('month')}
          >
            This Month
          </button>
        </div>
      </div>

      <div className="analytics-summary">
        <div className="metric">
          <span className="label">Total Bookings</span>
          <span className="value">{analytics?.total_bookings || 0}</span>
        </div>
        <div className="metric">
          <span className="label">Total Revenue</span>
          <span className="value">{formatCurrency(analytics?.total_revenue || 0)}</span>
        </div>
        <div className="metric">
          <span className="label">Avg. Booking Value</span>
          <span className="value">
            {formatCurrency(analytics?.average_booking_value || 0)}
          </span>
        </div>
      </div>

      {/* Top Services */}
      <div className="top-lists">
        <div className="top-services">
          <h3>Top Services</h3>
          <ul>
            {analytics?.top_services.map((service, index) => (
              <li key={service.service_id}>
                <span className="rank">{index + 1}</span>
                <span className="name">{service.name}</span>
                <span className="count">{service.count} bookings</span>
                <span className="revenue">{formatCurrency(service.revenue)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="top-practitioners">
          <h3>Top Practitioners</h3>
          <ul>
            {analytics?.top_practitioners.map((pract, index) => (
              <li key={pract.practitioner_id}>
                <span className="rank">{index + 1}</span>
                <span className="count">{pract.count} bookings</span>
                <span className="revenue">{formatCurrency(pract.revenue)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Trend Chart */}
      <div className="booking-trends">
        <h3>Booking Trends</h3>
        <div className="chart">
          {analytics?.booking_trends.map((trend) => (
            <div key={trend.date} className="bar-container">
              <div
                className="bar"
                style={{
                  height: `${Math.min(trend.count * 10, 100)}%`,
                }}
                title={`${trend.date}: ${trend.count} bookings, ${formatCurrency(trend.revenue)}`}
              />
              <span className="label">{trend.date.slice(-5)}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ==================== Bookings Management ====================
function BookingsManagement() {
  const [statusFilter, setStatusFilter] = useState<BookingStatus | undefined>();
  const { data: bookings, isLoading } = useAllBookings(statusFilter);
  const { mutate: cancelBooking, isPending: isCancelling } = useAdminCancelBooking();

  const handleCancel = (bookingId: string) => {
    if (window.confirm('Are you sure you want to cancel this booking?')) {
      cancelBooking({
        bookingId,
        reason: 'Cancelled by administrator',
      });
    }
  };

  return (
    <section className="bookings-section">
      <div className="section-header">
        <h2>Bookings</h2>
        <select
          value={statusFilter || ''}
          onChange={(e) => setStatusFilter(e.target.value as BookingStatus || undefined)}
        >
          <option value="">All Statuses</option>
          <option value="draft">Draft</option>
          <option value="pending">Pending</option>
          <option value="confirmed">Confirmed</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {isLoading ? (
        <div className="loading">Loading bookings...</div>
      ) : (
        <table className="bookings-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Customer</th>
              <th>Service</th>
              <th>Date</th>
              <th>Time</th>
              <th>Status</th>
              <th>Total</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {bookings?.map((booking) => (
              <tr key={booking.booking_id}>
                <td>{booking.booking_id.slice(0, 8)}</td>
                <td>{booking.customer?.email || 'N/A'}</td>
                <td>{booking.service?.name || 'N/A'}</td>
                <td>{booking.slot.date}</td>
                <td>{booking.slot.start_time}</td>
                <td>
                  <span className={`status-badge ${booking.status}`}>
                    {booking.status}
                  </span>
                </td>
                <td>{formatCurrency(booking.total_price)}</td>
                <td>
                  {booking.status === 'confirmed' && (
                    <button
                      className="cancel-btn"
                      onClick={() => handleCancel(booking.booking_id)}
                      disabled={isCancelling}
                    >
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ==================== User Management ====================
function UserManagement() {
  const { data: users, isLoading } = useUsers();
  const { mutate: updateRole } = useUpdateUserRole();
  const { mutate: updateStatus } = useUpdateUserStatus();

  const handleRoleChange = (userId: string, newRole: UserRole) => {
    updateRole({ userId, role: newRole });
  };

  const handleStatusToggle = (user: User) => {
    updateStatus({ userId: user.user_id, isActive: !user.is_active });
  };

  return (
    <section className="users-section">
      <h2>User Management</h2>

      {isLoading ? (
        <div className="loading">Loading users...</div>
      ) : (
        <table className="users-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Phone</th>
              <th>Role</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users?.map((user) => (
              <tr key={user.user_id}>
                <td>
                  {user.first_name} {user.last_name}
                </td>
                <td>{user.email}</td>
                <td>{user.phone || '-'}</td>
                <td>
                  <select
                    value={user.role}
                    onChange={(e) =>
                      handleRoleChange(user.user_id, e.target.value as UserRole)
                    }
                  >
                    <option value="customer">Customer</option>
                    <option value="practitioner">Practitioner</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
                <td>
                  <span className={`status ${user.is_active ? 'active' : 'inactive'}`}>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td>
                  <button
                    className={user.is_active ? 'deactivate-btn' : 'activate-btn'}
                    onClick={() => handleStatusToggle(user)}
                  >
                    {user.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
