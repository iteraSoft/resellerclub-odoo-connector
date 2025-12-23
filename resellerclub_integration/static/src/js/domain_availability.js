/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

/**
 * Domain Availability Checker Widget
 *
 * This widget allows checking domain availability directly from forms.
 */
export class DomainAvailabilityChecker extends Component {
    static template = "resellerclub_integration.DomainAvailabilityChecker";
    static props = {
        domainName: { type: String, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");

        this.state = useState({
            domainName: this.props.domainName || "",
            isChecking: false,
            results: null,
            error: null,
        });
    }

    async checkAvailability() {
        if (!this.state.domainName) {
            this.notification.add("Please enter a domain name", { type: "warning" });
            return;
        }

        this.state.isChecking = true;
        this.state.results = null;
        this.state.error = null;

        try {
            // Split domain name
            const parts = this.state.domainName.split('.');
            let sld, tlds;

            if (parts.length >= 2) {
                sld = parts[0];
                tlds = [parts.slice(1).join('.')];
            } else {
                sld = this.state.domainName;
                tlds = ['com', 'net', 'org', 'info', 'biz', 'co'];
            }

            const result = await this.rpc("/resellerclub/domain/check", {
                domain_name: sld,
                tlds: tlds,
            });

            if (result.success) {
                this.state.results = result.data;
            } else {
                this.state.error = result.error;
            }
        } catch (error) {
            this.state.error = error.message || "An error occurred";
        } finally {
            this.state.isChecking = false;
        }
    }

    getAvailabilityClass(status) {
        if (typeof status === 'object') {
            return status.status === 'available' ? 'o_rc_available' : 'o_rc_unavailable';
        }
        return status === 'available' ? 'o_rc_available' : 'o_rc_unavailable';
    }

    isAvailable(status) {
        if (typeof status === 'object') {
            return status.status === 'available';
        }
        return status === 'available';
    }
}

DomainAvailabilityChecker.template = "resellerclub_integration.DomainAvailabilityChecker";

// Template defined inline for simplicity
// In a full implementation, this would be in a separate XML file

/**
 * Domain Suggestion Widget
 */
export class DomainSuggestions extends Component {
    static template = "resellerclub_integration.DomainSuggestions";
    static props = {
        keyword: { type: String, optional: true },
        onSelect: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");

        this.state = useState({
            keyword: this.props.keyword || "",
            isLoading: false,
            suggestions: [],
        });
    }

    async getSuggestions() {
        if (!this.state.keyword || this.state.keyword.length < 3) {
            return;
        }

        this.state.isLoading = true;

        try {
            const result = await this.rpc("/resellerclub/domain/suggest", {
                keyword: this.state.keyword,
            });

            if (result.success) {
                this.state.suggestions = result.data || [];
            }
        } catch (error) {
            console.error("Failed to get suggestions:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    selectDomain(domain) {
        if (this.props.onSelect) {
            this.props.onSelect(domain);
        }
    }
}

// Register components
registry.category("components").add("DomainAvailabilityChecker", DomainAvailabilityChecker);
registry.category("components").add("DomainSuggestions", DomainSuggestions);
