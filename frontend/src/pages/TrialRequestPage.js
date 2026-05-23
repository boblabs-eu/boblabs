/**
 * Bob Labs — Trial request page.
 * Visitors fill a form to request trial access to the platform.
 */

import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { submitTrialRequest } from '../services/api';
import { useT, LanguageToggle } from '../i18n';

export default function TrialRequestPage() {
  const { t } = useT();
  const [form, setForm] = useState({ name: '', email: '', enterprise: '', role: '', purpose: '' });
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const update = (field) => (e) => setForm((prev) => ({ ...prev, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.email.trim()) {
      setError(t('trial.error.required'));
      return;
    }
    setError('');
    setLoading(true);
    try {
      await submitTrialRequest(form);
      setSubmitted(true);
    } catch {
      setError(t('trial.error.generic'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card" style={{ maxWidth: 520 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <Link to="/" className="login-brand">Bob Labs</Link>
          <LanguageToggle />
        </div>

        {submitted ? (
          <>
            <h1>{t('trial.success.title')}</h1>
            <p className="login-subtitle">{t('trial.success.body')}</p>
            <Link to="/" className="login-btn" style={{ display: 'block', textAlign: 'center', marginTop: '1.5rem' }}>
              {t('trial.success.back')}
            </Link>
          </>
        ) : (
          <>
            <h1>{t('trial.title')}</h1>
            <p className="login-subtitle">{t('trial.intro')}</p>
            <form onSubmit={handleSubmit}>
              <input
                type="text"
                value={form.name}
                onChange={update('name')}
                placeholder={t('trial.field.name')}
                className="login-input"
                required
              />
              <input
                type="email"
                value={form.email}
                onChange={update('email')}
                placeholder={t('trial.field.email')}
                className="login-input"
                required
              />
              <input
                type="text"
                value={form.enterprise}
                onChange={update('enterprise')}
                placeholder={t('trial.field.company')}
                className="login-input"
              />
              <input
                type="text"
                value={form.role}
                onChange={update('role')}
                placeholder={t('trial.field.role')}
                className="login-input"
              />
              <textarea
                value={form.purpose}
                onChange={update('purpose')}
                placeholder={t('trial.field.purpose')}
                className="login-input"
                rows={4}
                style={{ resize: 'vertical' }}
              />
              {error && <p className="login-error">{error}</p>}
              <button type="submit" className="login-btn" disabled={loading}>
                {loading ? t('trial.submit.loading') : t('trial.submit')}
              </button>
            </form>
            <p className="login-footer-text">
              {t('trial.haveToken')} <Link to="/login">{t('trial.signIn')}</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
