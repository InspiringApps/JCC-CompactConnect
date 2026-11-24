//
//  LicenseHistory.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { Component, mixins, toNative } from 'vue-facing-decorator';
import { reactive, computed, nextTick } from 'vue';
import MixinApplicationSection, { SelectOption } from '@pages/Applications/_mixins/applicationSection.mixin';
import ApplicationSectionLayout from '@components/ApplicationSectionLayout/ApplicationSectionLayout.vue';
import InputText from '@components/Forms/InputText/InputText.vue';
import InputSelect from '@components/Forms/InputSelect/InputSelect.vue';
import InputDate from '@components/Forms/InputDate/InputDate.vue';
import InputButton from '@components/Forms/InputButton/InputButton.vue';
import InputSubmit from '@components/Forms/InputSubmit/InputSubmit.vue';
import Modal from '@components/Modal/Modal.vue';
import MockPopulate from '@components/Forms/MockPopulate/MockPopulate.vue';
import {
    ApplicationLicense,
    ApplicationLicenseStatus,
    ApplicationSection,
    ApplicationType
} from '@models/Application/Application.model';
import { FormInput } from '@models/FormInput/FormInput.model';
import { State } from '@models/State/State.model';
import { dateDisplay } from '@models/_formatters/date';
import Joi from 'joi';

@Component({
    name: 'LicenseHistory',
    components: {
        ApplicationSectionLayout,
        InputText,
        InputSelect,
        InputDate,
        InputButton,
        InputSubmit,
        Modal,
        MockPopulate,
    },
})
class LicenseHistory extends mixins(MixinApplicationSection) {
    //
    // Data
    //
    sectionKey = ApplicationSection.LICENSE_HISTORY;
    licenseFormData: any = {};
    isLicenseModalOpen = false;
    editLicenseIndex: number | null = null;
    openMenuIndex: number | null = null;

    //
    // Computed
    //
    get isApit(): boolean {
        return (this.applicationData.types || []).includes(ApplicationType.APIT);
    }

    get isTap(): boolean {
        return (this.applicationData.types || []).includes(ApplicationType.TAP);
    }

    get licenses(): Array<ApplicationLicense> {
        return (this.formData.licenses?.value as Array<ApplicationLicense>) || [];
    }

    get licenseStatusOptions(): Array<SelectOption> {
        return [
            { value: '', name: this.$t('application.selectStatus') },
            ...Object.values(ApplicationLicenseStatus).map((status) => ({
                value: status,
                name: this.$t(`application.licenseStatusOptions.${status}`),
            })),
        ];
    }

    get licenseModalTitle(): string {
        return (this.editLicenseIndex === null)
            ? this.$t('application.addLicense')
            : this.$t('application.editLicense');
    }

    get licenseSubmitLabel(): string {
        return (this.editLicenseIndex === null)
            ? this.$t('application.addLicense')
            : this.$t('application.updateLicense');
    }

    //
    // Methods
    //
    initFormInputs(): void {
        const { ePassport = {}, ipc = {}, licenses = [] } = this.sectionData;
        const formData: any = {
            licenses: new FormInput({
                id: 'licenses',
                name: 'licenses',
                value: licenses.map((license) => ({ ...license })),
                validation: Joi.array().min(1).messages({
                    'array.min': this.$t('application.licensesRequired'),
                }),
            }),
            submit: new FormInput({
                isSubmitInput: true,
                id: 'submit-license-history',
            }),
        };

        if (this.isApit) {
            formData.ePassportNumber = new FormInput({
                id: 'e-passport-number',
                name: 'e-passport-number',
                label: computed(() => this.$t('application.mobilityNumberLabel')),
                placeholder: computed(() => this.$t('application.ePassportPlaceholder')),
                autocomplete: 'off',
                value: ePassport?.mobilityNumber || '',
                validation: this.textValidation(),
            });
            formData.ePassportIssueDate = new FormInput({
                id: 'e-passport-issue-date',
                name: 'e-passport-issue-date',
                label: computed(() => this.$t('application.issueDateLabel')),
                placeholder: 'MM/DD/YYYY',
                value: ePassport?.issueDate || '',
                validation: this.dateValidation(),
            });
        }

        if (this.isTap) {
            formData.ipcNumber = new FormInput({
                id: 'ipc-number',
                name: 'ipc-number',
                label: computed(() => this.$t('application.mobilityNumberLabel')),
                placeholder: computed(() => this.$t('application.ipcPlaceholder')),
                autocomplete: 'off',
                value: ipc?.mobilityNumber || '',
                validation: this.textValidation(),
            });
            formData.ipcIssueDate = new FormInput({
                id: 'ipc-issue-date',
                name: 'ipc-issue-date',
                label: computed(() => this.$t('application.issueDateLabel')),
                placeholder: 'MM/DD/YYYY',
                value: ipc?.issueDate || '',
                validation: this.dateValidation(),
            });
        }

        this.formData = reactive(formData);
        this.watchFormInputs();
    }

    initLicenseFormInputs(license: ApplicationLicense = {}): void {
        this.licenseFormData = reactive({
            state: new FormInput({
                id: 'license-state',
                name: 'license-state',
                label: computed(() => this.$t('application.jurisdictionLabel')),
                value: license.state || '',
                valueOptions: this.stateOptions,
                validation: Joi.string().required().messages(this.joiMessages.string),
            }),
            issueDate: new FormInput({
                id: 'license-issue-date',
                name: 'license-issue-date',
                label: computed(() => this.$t('application.issueDateLabel')),
                placeholder: 'MM/DD/YYYY',
                value: license.issueDate || '',
                validation: this.dateValidation(),
            }),
            licenseNumber: new FormInput({
                id: 'license-number',
                name: 'license-number',
                label: computed(() => this.$t('application.licenseNumberLabel')),
                autocomplete: 'off',
                value: license.licenseNumber || '',
                validation: this.textValidation(),
            }),
            status: new FormInput({
                id: 'license-status',
                name: 'license-status',
                label: computed(() => this.$t('application.licenseStatusLabel')),
                value: license.status || '',
                valueOptions: this.licenseStatusOptions,
                validation: Joi.string().required().messages(this.joiMessages.string),
            }),
            submit: new FormInput({
                isSubmitInput: true,
                id: 'submit-license',
                shouldHideMargin: true,
            }),
        });
    }

    licenseStateName(license: ApplicationLicense): string {
        return (license.state) ? new State({ abbrev: license.state }).name() : '';
    }

    licenseIssueDate(license: ApplicationLicense): string {
        return dateDisplay(license.issueDate || '');
    }

    toggleLicenseMenu(index: number): void {
        this.openMenuIndex = (this.openMenuIndex === index) ? null : index;
    }

    async openLicenseModal(index: number | null = null): Promise<void> {
        const license = (index === null) ? {} : this.licenses[index];

        this.openMenuIndex = null;
        this.editLicenseIndex = index;
        this.initLicenseFormInputs(license);
        this.isLicenseModalOpen = true;
        await nextTick();
        (document.getElementById('license-state') as HTMLElement)?.focus();
    }

    closeLicenseModal(): void {
        this.isLicenseModalOpen = false;
        this.editLicenseIndex = null;
        this.licenseFormData = {};
    }

    saveLicense(): void {
        const licenseInputs: Array<FormInput> = ['state', 'issueDate', 'licenseNumber', 'status']
            .map((key) => this.licenseFormData[key]);

        licenseInputs.forEach((formInput) => {
            formInput.isTouched = true;
            formInput.validate();
        });

        if (licenseInputs.every((formInput) => formInput.isValid)) {
            const {
                state, issueDate, licenseNumber, status
            } = this.licenseFormData;
            const license: ApplicationLicense = {
                state: state.value,
                issueDate: issueDate.value,
                licenseNumber: licenseNumber.value,
                status: status.value,
            };
            const licenses = [...this.licenses];

            if (this.editLicenseIndex === null) {
                licenses.push(license);
            } else {
                licenses.splice(this.editLicenseIndex, 1, license);
            }

            this.updateLicenses(licenses);
            this.closeLicenseModal();
        }
    }

    removeLicense(index: number): void {
        this.openMenuIndex = null;
        this.updateLicenses(this.licenses.filter((license, licenseIndex) => licenseIndex !== index));
    }

    updateLicenses(licenses: Array<ApplicationLicense>): void {
        const { licenses: licensesInput } = this.formData;

        licensesInput.value = licenses;
        licensesInput.isTouched = true;
        licensesInput.validate();
    }

    scrollToInput(formInput: FormInput): void {
        if (formInput.name === 'licenses') {
            this.scrollToElement('licenses-heading');
            (document.querySelector('.add-license-button input') as HTMLElement)?.focus();
        } else {
            const element = document.getElementsByName(formInput.name)[0] as HTMLElement | undefined;

            if (element && typeof element.scrollIntoView === 'function') {
                element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                element.focus();
            }
        }
    }

    mockPopulate(): void {
        const { formData } = this;

        this.updateLicenses([
            {
                state: 'co',
                issueDate: '2015-06-01',
                licenseNumber: 'PSY-0012345',
                status: ApplicationLicenseStatus.ACTIVE,
            },
            {
                state: 'ne',
                issueDate: '2010-03-15',
                licenseNumber: 'PSY-0067890',
                status: ApplicationLicenseStatus.INACTIVE,
            },
        ]);

        if (this.isApit) {
            formData.ePassportNumber.value = 'EP-118420';
            formData.ePassportIssueDate.value = '2020-01-15';
        }

        if (this.isTap) {
            formData.ipcNumber.value = 'IPC-118420';
            formData.ipcIssueDate.value = '2020-01-15';
        }
    }

    async mockPopulateLicense(): Promise<void> {
        const { licenseFormData } = this;

        licenseFormData.state.value = 'co';
        licenseFormData.issueDate.value = '2015-06-01';
        licenseFormData.licenseNumber.value = 'PSY-0012345';
        licenseFormData.status.value = ApplicationLicenseStatus.ACTIVE;
        await nextTick();
        ['state', 'issueDate', 'licenseNumber', 'status'].forEach((key) => licenseFormData[key].validate());
        this.scrollToElement(licenseFormData.submit.id);
    }

    prepSectionRequestData(): object {
        const { formValues, sectionData } = this;

        return {
            ePassport: (this.isApit)
                ? { mobilityNumber: formValues.ePassportNumber, issueDate: formValues.ePassportIssueDate }
                : sectionData.ePassport || null,
            ipc: (this.isTap)
                ? { mobilityNumber: formValues.ipcNumber, issueDate: formValues.ipcIssueDate }
                : sectionData.ipc || null,
            licenses: formValues.licenses,
        };
    }
}

export default toNative(LicenseHistory);

// export default LicenseHistory;
