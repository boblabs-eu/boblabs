/**
 * Bob Labs — Login page.
 * Users enter an access token to gain platform access.
 */

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { validateAccessToken } from '../services/api';
import { useT, LanguageToggle } from '../i18n';

export default function LoginPage() {
  const { t } = useT();
  const [accessToken, setAccessToken] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!accessToken.trim()) return;
    setError('');
    setLoading(true);
    try {
      const res = await validateAccessToken(accessToken.trim());
      login(res.data.access_token);
      navigate('/dashboard');
    } catch {
      setError(t('login.error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <Link to="/" className="login-brand">Bob Labs</Link>
          <LanguageToggle />
        </div>
        <h1>{t('login.title')}</h1>
        <p className="login-subtitle">{t('login.intro')}</p>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={accessToken}
            onChange={(e) => setAccessToken(e.target.value)}
            placeholder={t('login.placeholder')}
            className="login-input"
            autoFocus
          />
          {error && <p className="login-error">{error}</p>}
          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? t('login.submit.loading') : t('login.submit')}
          </button>
        </form>
        <p className="login-footer-text">
          {t('login.noToken')} <Link to="/request-trial">{t('login.requestTrial')}</Link>
        </p>
      </div>
    </div>
  );
}
