import { useState } from 'react';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Monitor from './pages/Monitor';
import Competitors from './pages/Competitors';
import Status from './pages/Status';
import type { Page } from './types';

export default function App() {
  const [page, setPage] = useState<Page>('overview');

  return (
    <Layout currentPage={page} onNavigate={setPage}>
      {page === 'overview' && <Overview />}
      {page === 'monitor' && <Monitor />}
      {page === 'competitors' && <Competitors />}
      {page === 'status' && <Status />}
    </Layout>
  );
}
