from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, User, Subscription, Transaction
import stripe
import razorpay
from datetime import datetime, timedelta
import os

payments_bp = Blueprint('payments', __name__)

# --- CONFIGURATION (PLACEHOLDERS) ---
# STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_PLACEHOLDER')
# STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', 'pk_test_PLACEHOLDER')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
if not STRIPE_SECRET_KEY or 'PLACEHOLDER' in STRIPE_SECRET_KEY:
    print("WARNING: Stripe Secret Key is missing or default!")
stripe.api_key = STRIPE_SECRET_KEY

RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', 'rzp_test_PLACEHOLDER')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', 'secret_PLACEHOLDER')
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Plan details mapping
PLANS = {
    'basic_299': {'amount': 299, 'name': 'Basic Plan', 'currency': 'INR'},
    'pro_499': {'amount': 499, 'name': 'Pro Plan', 'currency': 'INR'},
    'school_1200': {'amount': 1200, 'name': 'School Plan', 'currency': 'INR'}
}

@payments_bp.route('/pricing')
def pricing():
    return render_template('pricing.html', 
                          stripe_key=STRIPE_PUBLISHABLE_KEY, 
                          razorpay_key=RAZORPAY_KEY_ID)

# --- CHECKOUT ROUTES ---

@payments_bp.route('/checkout/stripe/<plan_id>', methods=['POST'])
@login_required
def stripe_checkout(plan_id):
    plan = PLANS.get(plan_id)
    if not plan:
        flash('Invalid plan selected.')
        return redirect(url_for('payments.pricing'))
        
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': plan['currency'],
                    'product_data': {'name': plan['name']},
                    'unit_amount': plan['amount'] * 100, # Stripe uses cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payments.payment_success', provider='stripe', plan_id=plan_id, _external=True) + '&session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('payments.pricing', _external=True),
            client_reference_id=str(current_user.id),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        flash(f'Error creating Stripe session: {str(e)}')
        return redirect(url_for('payments.pricing'))

@payments_bp.route('/checkout/razorpay/<plan_id>', methods=['POST'])
@login_required
def razorpay_checkout(plan_id):
    plan = PLANS.get(plan_id)
    if not plan:
        return jsonify({'error': 'Invalid plan'}), 400
        
    try:
        order_amount = plan['amount'] * 100 # Razorpay uses paise
        order_currency = 'INR'
        order_receipt = f'order_{current_user.id}_{int(datetime.utcnow().timestamp())}'
        
        razorpay_order = razorpay_client.order.create({
            'amount': order_amount,
            'currency': order_currency,
            'receipt': order_receipt,
            'payment_capture': '1'
        })
        
        return jsonify({
            'order_id': razorpay_order['id'],
            'amount': order_amount,
            'key': RAZORPAY_KEY_ID,
            'name': "Panun School",
            'description': plan['name'],
            'prefill': {'name': current_user.username, 'email': current_user.email},
            'callback_url': url_for('payments.payment_success', provider='razorpay', plan_id=plan_id, _external=True)
        })
    except Exception as e:
         return jsonify({'error': str(e)}), 500

# --- SUCCESS & ACTIVATION ---

@payments_bp.route('/payment/success/<provider>/<plan_id>')
@login_required
def payment_success(provider, plan_id):
    # Verify payment if needed (e.g. check Stripe session status or Razorpay signature)
    # For now, we assume success based on the callback for simplicity in this step.
    # In production, verify signatures!
    
    plan = PLANS.get(plan_id)
    if not plan:
        flash("Invalid Plan Activation Attempt.")
        return redirect(url_for('index'))

    # Deactivate old subscription
    old_sub = Subscription.query.filter_by(user_id=current_user.id, is_active=True).first()
    if old_sub:
        old_sub.is_active = False
    
    # Create new subscription
    new_sub = Subscription(
        user_id=current_user.id,
        plan_type=plan_id,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=30), # Monthly
        is_active=True
    )
    db.session.add(new_sub)
    db.session.commit()
    
    # Update User's active subscription ID
    current_user.active_subscription_id = new_sub.id
    db.session.commit()
    
    # Record Transaction (Placeholder ID)
    txn_id = request.args.get('session_id') or request.args.get('razorpay_payment_id') or f"txn_{int(datetime.utcnow().timestamp())}"
    
    txn = Transaction(
        user_id=current_user.id,
        amount=plan['amount'],
        currency=plan['currency'],
        provider=provider,
        transaction_id=txn_id,
        status='success'
    )
    db.session.add(txn)
    db.session.commit()
    
    flash(f'Successfully upgraded to {plan["name"]}!')
    return redirect(url_for('dashboard')) # Corrected route name
