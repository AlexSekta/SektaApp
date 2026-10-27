import {
  BrowserRouter,
  Routes,
  Route,
  Navigate
} from "react-router-dom";


import Layout from "./Layout";
import { AuthProvider } from "./AuthContext";
import ProtectedRoute from "./ProtectedRoute";
import Login from "./Login";
import Register from "./Register";
import ForgotPassword from "./ForgotPassword";
import ResetPassword from "./ResetPassword";

import MasterProducts from "./MasterProducts";

import Stocks from "./Stocks";

import Registry from "./Registry";

import Analytics from "./Analytics";
import WeeklyReport from "./WeeklyReport";
import UnitEconomy from "./UnitEconomy";


import CustomerCommunication from "./CustomerCommunication";
import Settings from "./Settings";
import Profile from "./Profile";



function App() {


  return (


    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >


          <Route
            index
            element={
              <Navigate to="/products" />
            }
          />



          <Route
            path="products"
            element={
              <MasterProducts />
            }
          />



          <Route
            path="stocks"
            element={
              <Stocks />
            }
          />



          <Route
            path="registry"
            element={
              <Registry />
            }
          />



          <Route
            path="analytics"
            element={<Analytics />}
          />
          <Route
            path="analytics/weekly"
            element={<WeeklyReport />}
          />

          <Route
            path="analytics/unit-economy"
            element={<UnitEconomy />}
          />


          <Route
            path="reviews"
            element={
              <CustomerCommunication />
            }
          />
          <Route path="profile" element={<Profile />} />
          <Route
            path="settings"
            element={<Settings />}
          />


          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>


  );

}


export default App;