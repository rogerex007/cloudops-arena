import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import LeaderboardScreen from './LeaderboardScreen';
import './styles.css';
import './lab-experience.css';

const screenMatch=window.location.pathname.match(/^\/clasificacion\/([A-Za-z0-9_-]{32})\/?$/);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{screenMatch?<LeaderboardScreen share={screenMatch[1]}/>:<App />}</React.StrictMode>,
);
